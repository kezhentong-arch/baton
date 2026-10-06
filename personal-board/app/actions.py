"""Every write to the board. All the rules live here; the page, the HTTP API and the MCP server only pass
requests through.

`action_specs()` says what each action does and what it needs — the AI asks follow-up questions from it.
`apply_action` validates and writes, and raises ActionError with a plain-language reason (fail first).
"""
from __future__ import annotations

import re
import sqlite3
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime, timedelta

from app import points, settings
from app.i18n import LANGS, t
from app.model import (FUTURE_TOLERANCE, LOG_KINDS, SYNC_KINDS, SYNC_STATES, TOOLS, iso, kind_label, local_day,
                       local_text, parse_ts, sync_label, version_key)
from app.store import find_goal, next_birth, set_meta


class ActionError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


@dataclass
class Result:
    ok: bool = True
    ids: list[int] | None = None
    goal_id: int | None = None
    gnum: str | None = None

    def as_dict(self) -> dict:
        return {"ok": self.ok, "ids": self.ids or [], "goal_id": self.goal_id, "gnum": self.gnum}


COMMON = ("occurred_at", "task", "tool")

# name → (required, optional). The descriptions come from the translation table (act.<name>).
_SPECS: dict[str, tuple[list[str], list[str]]] = {
    "goal_create": (["title", "line"],
                    ["parent_gnum", "next_step", "due", "long_term", "gnum", "point_at", "point_zone", "repeat", "what", *COMMON]),
    "goal_update": (["goal"], ["title", "next_step", "blocker", "version_name", "gnum", "due", "line", "parent_gnum",
                               "status", "reason", "occurred_at", "point_at", "point_zone", "repeat", "what", "done_what"]),
    "log": (["goal", "text"], ["kind", "stage", "version", *COMMON]),
    "stage_start": (["goal", "stage"], ["text", *COMMON]),
    "stage_end": (["goal", "stage"], ["text", *COMMON]),
    "complete": (["goal"], ["text", "done_what", *COMMON]),
    "release": (["goal", "version"], ["text", *COMMON]),
    "point_done": (["goal"], ["occurrence", "text", *COMMON]),
    "point_reminded": ([], ["task", "tool"]),   # accepted but not stored, so an AI that always sends task / tool is not rejected
    "todo_add": (["text"], ["goal"]),
    "todo_done": (["todo_id"], []),
    "note_add": (["text"], ["goal"]),
    "note_resolve": (["note_id", "summary"], []),
    "sync_mark": (["entry_ids", "status"], ["team_ref"]),
    "void": (["entry_id", "reason"], []),
}


def action_specs() -> dict[str, dict]:
    """What each action does, its required and optional fields — in the configured language."""
    zone = settings.tz_label()
    letter = settings.person()["letter"]
    return {name: {"what": t(f"act.{name}", zone=zone, letter=letter), "required": list(req), "optional": list(opt)}
            for name, (req, opt) in _SPECS.items()}


def common_fields() -> dict[str, str]:
    return {k: t(f"act.common.{k}") for k in COMMON}


def values() -> dict:
    """The value tables: lines, stages, entry kinds, tools, sync states, point zones, repeats."""
    return {"line": settings.line_names(), "stage": settings.stage_names(),
            "kind": {k: kind_label(k) for k in LOG_KINDS}, "tool": list(TOOLS),
            "sync_status": {k: sync_label(k) for k in SYNC_STATES if k != "pending"},
            "point_zone": points.zone_values(), "repeat": {"monthly": t("point.repeat_monthly_desc")},
            "common": common_fields()}


def _join(items) -> str:
    return t("sep").join(str(x) for x in items)


def _int(params: dict, key: str) -> int:
    try:
        return int(str(params[key]).strip().lstrip("#"))
    except (TypeError, ValueError):
        raise ActionError(t("err.int", key=key, value=repr(params[key]))) from None


def _goal(conn: sqlite3.Connection, key) -> sqlite3.Row:
    row = find_goal(conn, key)
    if row is None:
        raise ActionError(t("err.no_goal", key=key, example=f"{settings.person()['letter']}19"))
    return row


def _when(params: dict, now: datetime) -> datetime:
    raw = params.get("occurred_at")
    if raw in (None, ""):
        return now
    try:
        dt = parse_ts(str(raw))
    except ValueError as e:
        raise ActionError(t("err.bad_time", error=e)) from None
    if dt - now > FUTURE_TOLERANCE:
        raise ActionError(t("err.future", value=raw))
    return dt


def _stage(params: dict, required: bool) -> str | None:
    st = params.get("stage")
    names = settings.stage_names()
    if st in (None, ""):
        if required:
            raise ActionError(t("err.stage_required", stages=_join(names)))
        return None
    if st not in names:
        raise ActionError(t("err.bad_stage", stages=_join(names), value=repr(st)))
    return st


_DUE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}( \d{2}:\d{2})?$")


def _due(params: dict) -> str | None:
    raw = str(params.get("due") or "").strip().replace("T", " ")
    if not raw:
        return None
    if not _DUE_RE.match(raw):
        raise ActionError(t("err.bad_due", zone=settings.tz_label(), value=repr(raw)))
    return raw


def _tool(params: dict) -> str:
    tool = str(params.get("tool") or "")
    if tool and tool not in TOOLS:
        raise ActionError(t("err.bad_tool", tools=_join(TOOLS), value=repr(tool)))
    return tool


def _truthy(v) -> bool:
    return str(v or "") in ("1", "true", "True")


def open_stages(conn: sqlite3.Connection, goal_id: int) -> dict[str, datetime]:
    """Stages open on a goal → when each started. Replays stage_start / stage_end in order of occurrence
    (voided entries skipped)."""
    opened: dict[str, datetime] = {}
    rows = conn.execute("SELECT stage, kind, occurred_at FROM entries WHERE goal_id=? AND voided_at IS NULL "
                        "AND kind IN ('stage_start','stage_end') ORDER BY occurred_at, id", (goal_id,))
    for r in rows:
        if r["kind"] == "stage_start":
            opened[r["stage"]] = parse_ts(r["occurred_at"])
        else:
            opened.pop(r["stage"], None)
    return opened


def _no_push(conn: sqlite3.Connection, goal_id: int) -> bool:
    """The goal's creation entry is marked "not pushed" = this row stays off the team board (a personal
    long-running row the team board does not show)."""
    row = conn.execute("SELECT sync FROM entries WHERE goal_id=? AND kind='goal_create' AND voided_at IS NULL "
                       "ORDER BY id LIMIT 1", (goal_id,)).fetchone()
    return bool(row) and row["sync"] == "skip"


# Length limits of the goal summary. `what` becomes the team board's note (500) and `done_what` is 1000 on
# both sides; checked here so a push at wrap-up is not the first place it fails.
SUMMARY_MAX = {"what": 500, "done_what": 1000}


def _summary(params: dict, key: str) -> str:
    text = str(params.get(key) or "").strip()
    if len(text) > SUMMARY_MAX[key]:
        raise ActionError(t("err.summary_long", label=t(f"label.{key}"), max=SUMMARY_MAX[key], n=len(text)))
    return text


def _summary_mark(key: str, lang: str | None = None) -> str:
    """The prefix a "summary edited" entry uses for one field, e.g. "Edited "What": "."""
    return t("text.summary_edit", lang=lang, label=t(f"label.{key}", lang=lang), value="")


def _on_team(conn: sqlite3.Connection, goal: sqlite3.Row) -> bool:
    """The goal is already on the team board (created there and pulled in, or created here and pushed).
    A goal not pushed yet needs no separate "summary edited" entry: the create / complete push carries
    the current text."""
    if not settings.is_team_line(goal["line"]) or points.is_point(goal) or _no_push(conn, goal["id"]):
        return False
    if goal["source"] == "team" or goal["team_id"] is not None:
        return True
    row = conn.execute("SELECT sync FROM entries WHERE goal_id=? AND kind='goal_create' AND voided_at IS NULL ORDER BY id LIMIT 1",
                       (goal["id"],)).fetchone()
    return bool(row) and row["sync"] == "pushed"


def _bump_version(conn: sqlite3.Connection, goal: sqlite3.Row, version: str, when: datetime, eid: int, backfill: bool) -> None:
    """Change the version badge of a long-running row. The badge is always the highest-numbered version,
    whatever order versions were closed in: two conversations working on two small versions of the same row
    in parallel must not let the lower one, closed later, take the badge back; nor may a backfilled old one.

    When the new version or the current badge has no number to compare, fall back to time: the badge changes
    only if this version is the latest (ties broken by entry order). A badge set by hand has no entry and no
    known moment, so a backfill leaves such a badge alone."""
    new, cur = version_key(version), version_key(goal["version_name"])
    if new is not None and cur is not None:
        if new >= cur:
            conn.execute("UPDATE goals SET version_name=? WHERE id=?", (version, goal["id"]))
        return
    if backfill and goal["version_name"] and not conn.execute(
            "SELECT 1 FROM entries WHERE goal_id=? AND version=? AND voided_at IS NULL AND id<>?",
            (goal["id"], goal["version_name"], eid)).fetchone():
        return
    later = conn.execute("SELECT 1 FROM entries WHERE goal_id=? AND version IS NOT NULL AND voided_at IS NULL AND id<>?"
                         " AND (occurred_at>? OR (occurred_at=? AND id>?))",
                         (goal["id"], eid, iso(when), iso(when), eid)).fetchone()
    if later is None:
        conn.execute("UPDATE goals SET version_name=? WHERE id=?", (version, goal["id"]))


def _version_of(conn: sqlite3.Connection, goal: sqlite3.Row, params: dict) -> str:
    version = str(params.get("version") or "").strip()
    if not version:
        raise ActionError(t("err.need_version"))
    if not goal["long_term"]:
        raise ActionError(t("err.not_long_term", gnum=goal["gnum"]))
    if conn.execute("SELECT 1 FROM entries WHERE goal_id=? AND version=? AND voided_at IS NULL", (goal["id"], version)).fetchone():
        raise ActionError(t("err.version_closed", gnum=goal["gnum"], version=version))
    return version


def _insert_entry(conn: sqlite3.Connection, goal: sqlite3.Row, *, kind: str, stage: str | None, text: str,
                  params: dict, when: datetime, now: datetime, occurrence: str | None = None, version: str | None = None) -> int:
    # A point task's tick may predate the goal: the task is set up on the 3rd, but the 1st was really paid on the 1st.
    if goal["source"] == "local" and kind != "point_done" and when < parse_ts(goal["created_at"]):
        raise ActionError(t("err.before_create", created=goal["created_at"]))
    # Only events on a team line are ever pushed. A row whose creation was marked "not pushed" keeps its later
    # stage entries out of the unpushed list too.
    syncable = kind in SYNC_KINDS and settings.is_team_line(goal["line"])
    if syncable and kind != "goal_create" and _no_push(conn, goal["id"]):
        syncable = False
    sync, ref = None, ""
    if syncable:
        if params.get("_sync") in SYNC_STATES:   # internal: seeding facts that are already on the team board
            sync = params["_sync"]
        elif settings.team_enabled():            # no team board configured → nothing is ever marked "unpushed"
            if points.is_point(goal):            # point tasks are marked "not pushed" from the start
                sync, ref = "skip", t("point.no_push")
            else:
                sync = "pending"
    cur = conn.execute(
        "INSERT INTO entries(goal_id, stage, kind, text, task, tool, occurred_at, recorded_at, sync, synced_at, team_ref, occurrence, version)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (goal["id"], stage, kind, text, str(params.get("task") or ""), _tool(params), iso(when), iso(now), sync,
         iso(when) if sync == "pushed" else (iso(now) if sync == "skip" else None),  # a seeded "pushed" fact was pushed when it happened
         ref, occurrence, version))
    conn.execute("UPDATE goals SET updated_at=? WHERE id=?", (iso(now), goal["id"]))
    return int(cur.lastrowid)


def apply_action(conn: sqlite3.Connection, action: str, params: dict, now: datetime, *, internal: bool = False,
                 commit: bool = True) -> Result:
    """internal=True is for in-package scripts (seeding) only and allows `_sync` to mark entries directly.
    Requests from the page and from MCP may not — that would bypass the human's nod at wrap-up."""
    spec = _SPECS.get(action)
    if spec is None:
        raise ActionError(t("err.no_action", action=action, actions=_join(_SPECS)))
    if "_sync" in params and not internal:
        raise ActionError(t("err.internal_sync"))
    required, optional = spec
    missing = [k for k in required if params.get(k) in (None, "", [])]
    if missing:
        raise ActionError(t("err.missing", action=action, keys=_join(missing)))
    unknown = set(params) - set(required) - set(optional) - {"_sync"}
    if unknown:
        raise ActionError(t("err.unknown", action=action, keys=_join(sorted(unknown))))
    if not conn.in_transaction:
        # Take the write lock before reading the birth-number watermark: when two conversations create a goal at
        # the same moment the second waits for the first to commit instead of computing the same number.
        conn.execute("BEGIN IMMEDIATE")
    try:
        with conn if commit else nullcontext():
            return _HANDLERS[action](conn, params, now)
    except sqlite3.IntegrityError as e:
        raise ActionError(t("err.conflict", error=e)) from None


def _goal_create(conn, params, now) -> Result:
    line = params["line"]
    if not settings.is_line(line):
        raise ActionError(t("err.bad_line", lines=_join(settings.line_names()), value=repr(line)))
    when = _when(params, now)
    parent = params.get("parent_gnum") or None
    if parent:
        parent = _goal(conn, parent)["gnum"]   # a birth number is stored as the display number so the tree links up
    gnum = params.get("gnum") or None
    if gnum and conn.execute("SELECT 1 FROM goals WHERE gnum=? OR birth=?", (gnum, gnum)).fetchone():
        raise ActionError(t("err.exists", gnum=gnum))
    me = conn.execute("SELECT value FROM meta WHERE key='person'").fetchone()
    owner = me["value"] if me else settings.person()["id"]
    birth = None
    if not gnum:   # a goal given an explicit number (example E numbers, seeded team goals) gets no birth number
        birth = gnum = next_birth(conn, settings.person()["letter"])
    point_at, zone, repeat = _point_rule(params, None)
    if point_at is None and ("point_zone" in params or "repeat" in params):
        raise ActionError(t("err.point_needs_at"))
    if point_at is not None and (_due(params) or _truthy(params.get("long_term"))):
        raise ActionError(t("err.point_no_due"))
    what = _summary(params, "what")
    if what and point_at is not None:
        raise ActionError(t("err.point_no_what"))
    cur = conn.execute(
        "INSERT INTO goals(gnum, birth, line, title, owner, parent_gnum, next_step, long_term, due, baseline_due,"
        " point_at, point_zone, point_repeat, what, created_at, updated_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (gnum, birth, line, str(params["title"]).strip(), owner, parent, str(params.get("next_step") or ""),
         1 if _truthy(params.get("long_term")) else 0, _due(params), _due(params),
         iso(point_at) if point_at else None, zone, repeat, what or None, iso(when), iso(now)))
    gid = int(cur.lastrowid)
    goal = _goal(conn, gnum)
    eid = _insert_entry(conn, goal, kind="goal_create", stage=None, text=t("text.create", title=goal["title"]),
                        params=params, when=when, now=now)
    return Result(ids=[eid], goal_id=gid, gnum=gnum)


def _goal_update(conn, params, now) -> Result:
    goal = _goal(conn, params["goal"])
    sets: dict[str, object] = {}
    ids: list[int] = []
    for k in ("title", "next_step", "blocker", "version_name"):
        if k in params:
            sets[k] = str(params[k])
    changed = []   # summary fields that changed: a goal already on the team board gets one "summary edited" entry to push
    for k in ("what", "done_what"):
        if k not in params:
            continue
        text = _summary(params, k)
        if k == "what" and text and points.is_point(goal):
            raise ActionError(t("err.point_what", gnum=goal["gnum"]))
        if k == "done_what" and text and goal["status"] != "done":
            if goal["long_term"]:
                raise ActionError(t("err.done_what_long_term", gnum=goal["gnum"]))
            raise ActionError(t("err.done_what_not_done", gnum=goal["gnum"]))
        if text != (goal[k] or ""):
            sets[k] = text or None
            changed.append(k)
    if "gnum" in params and params["gnum"] != goal["gnum"]:
        if conn.execute("SELECT 1 FROM goals WHERE gnum=? OR (birth=? AND id<>?)",
                        (params["gnum"], params["gnum"], goal["id"])).fetchone():
            raise ActionError(t("err.exists", gnum=params["gnum"]))
        sets["gnum"] = params["gnum"]
        conn.execute("UPDATE goals SET parent_gnum=? WHERE parent_gnum=?", (params["gnum"], goal["gnum"]))
    if "line" in params:
        if not settings.is_line(params["line"]):
            raise ActionError(t("err.bad_line", lines=_join(settings.line_names()), value=repr(params["line"])))
        sets["line"] = params["line"]
        if (settings.team_enabled() and settings.is_team_line(params["line"]) and not settings.is_team_line(goal["line"])
                and not points.is_point(goal)):
            # Moved from a personal line to a team line: its creation and stage entries, never marked before, now need pushing.
            kinds = ",".join(f"'{k}'" for k in SYNC_KINDS)
            conn.execute(f"UPDATE entries SET sync='pending' WHERE goal_id=? AND sync IS NULL AND voided_at IS NULL AND kind IN ({kinds})",
                         (goal["id"],))
    if "parent_gnum" in params:
        p = params["parent_gnum"] or None
        if p:
            p = _goal(conn, p)["gnum"]   # a birth number is stored as the display number
            if p == goal["gnum"]:
                raise ActionError(t("err.self_parent"))
        sets["parent_gnum"] = p
    if "status" in params:
        if points.is_point(goal) and params["status"] != "abandoned":
            # Un-cancelling would turn every occurrence missed around the cancellation into "overdue"; re-opening a
            # finished one-off would leave a done dot on an active row.
            raise ActionError(t("err.point_status", gnum=goal["gnum"]))
        if params["status"] == "done":
            raise ActionError(t("err.use_complete"))
        if params["status"] not in ("active", "abandoned"):
            raise ActionError(t("err.bad_status"))
        sets["status"] = params["status"]
        if params["status"] == "abandoned":
            when = _when(params, now)
            for st, started in open_stages(conn, goal["id"]).items():
                if when < started:
                    raise ActionError(t("err.abandon_before_stage", stage=st))
                ids.append(_insert_entry(conn, goal, kind="stage_end", stage=st, text=t("text.stage_end_abandon", stage=st),
                                         params=params, when=when, now=now))
            ids.append(_insert_entry(conn, goal, kind="abandon", stage=None,
                                     text=str(params.get("reason") or t("abandon.default")), params=params, when=when, now=now))
            sets["done_at"] = iso(when)  # abandoning has an end too: the grey bar stops here and leaves the view with time
        else:
            sets["done_at"] = None
    if "due" in params and points.is_point(goal):
        raise ActionError(t("err.point_due", gnum=goal["gnum"]))
    if "due" in params and _due(params) != goal["due"]:
        sets["due"] = _due(params)
        if goal["baseline_due"] is None and sets["due"]:   # no plan at creation: the first plan set is the baseline and later changes leave it
            sets["baseline_due"] = sets["due"]
        when = _when(params, now)
        reason = str(params.get("reason") or "")
        ids.append(_insert_entry(conn, goal, kind="due", stage=None,
                                 text=t("text.due", old=goal["due"] or t("text.unset"), new=params["due"] or t("text.unset"))
                                      + (t("text.reason", reason=reason) if reason else ""),
                                 params=params, when=when, now=now))
    if any(k in params for k in ("point_at", "point_zone", "repeat")):
        if not points.is_point(goal):
            raise ActionError(t("err.not_point", gnum=goal["gnum"]))
        if goal["status"] != "active":
            raise ActionError(t("err.point_closed_done" if goal["status"] == "done" else "err.point_closed_cancelled", gnum=goal["gnum"]))
        # The rule runs from point_at and past occurrences are computed from it on the fly: a new first moment
        # earlier than now would turn months already done into "overdue" under the new wall clock. So a rule can
        # only change from the next occurrence on; earlier ones stay. Changing just the zone needs a new point_at too.
        if params.get("point_at") in (None, ""):
            raise ActionError(t("err.point_at_required"))
        point_at, zone, repeat = _point_rule(params, goal)
        if point_at <= now:
            raise ActionError(t("err.point_at_future", at=points.zone_text(point_at, zone)))
        before = points.rule_with_start(goal)
        sets.update({"point_at": iso(point_at), "point_zone": zone, "point_repeat": repeat})
        after = points.rule_with_start({**dict(goal), "point_at": iso(point_at), "point_zone": zone, "point_repeat": repeat})
        if after != before:
            reason = str(params.get("reason") or "")
            ids.append(_insert_entry(conn, goal, kind="note", stage=None,
                                     text=t("text.point_change", before=before, after=after) + (t("text.reason", reason=reason) if reason else ""),
                                     params=params, when=_when(params, now), now=now))
    if changed and _on_team(conn, goal):
        pending_complete = conn.execute("SELECT 1 FROM entries WHERE goal_id=? AND kind='complete' AND sync='pending' AND voided_at IS NULL",
                                        (goal["id"],)).fetchone()
        pushed = [k for k in changed if not (k == "done_what" and pending_complete)]   # "complete" not pushed yet: its push carries the current text
        if pushed:
            # Keep a single unpushed "summary edited" entry per goal and overwrite it on the next edit: two entries
            # would both push the latest text, and the team board would reject the second as "nothing to change",
            # leaving it unpushed forever.
            prev = conn.execute("SELECT id, text FROM entries WHERE goal_id=? AND kind='summary' AND sync='pending' AND voided_at IS NULL"
                                " ORDER BY id DESC LIMIT 1", (goal["id"],)).fetchone()
            keys = [k for k in ("what", "done_what")
                    if k in pushed or (prev and any(_summary_mark(k, lang) in prev["text"] for lang in LANGS))]
            text = t("text.semi").join(_summary_mark(k) + ((sets[k] if k in sets else goal[k]) or t("text.cleared")) for k in keys)
            when = _when(params, now)
            if prev is None:
                ids.append(_insert_entry(conn, goal, kind="summary", stage=None, text=text, params=params, when=when, now=now))
            else:
                conn.execute("UPDATE entries SET text=?, occurred_at=?, recorded_at=? WHERE id=?", (text, iso(when), iso(now), prev["id"]))
                ids.append(prev["id"])
    if not sets and not ids:
        raise ActionError(t("err.nothing"))
    if sets:
        sets["updated_at"] = iso(now)
        assign = ", ".join(f"{k}=?" for k in sets)
        conn.execute(f"UPDATE goals SET {assign} WHERE id=?", (*sets.values(), goal["id"]))
    g2 = _goal(conn, params.get("gnum") or goal["gnum"])
    return Result(ids=ids, goal_id=g2["id"], gnum=g2["gnum"])


def _log(conn, params, now) -> Result:
    goal = _goal(conn, params["goal"])
    kind = str(params.get("kind") or "result")
    if kind not in LOG_KINDS:
        raise ActionError(t("err.bad_kind"))
    version = None
    if str(params.get("version") or "").strip():
        if kind != "digest":
            raise ActionError(t("err.version_digest_only"))
        version = _version_of(conn, goal, params)
    when = _when(params, now)
    eid = _insert_entry(conn, goal, kind=kind, stage=_stage(params, False), text=str(params["text"]).strip(),
                        params=params, when=when, now=now, version=version)
    if version:
        _bump_version(conn, goal, version, when, eid, params.get("occurred_at") not in (None, ""))
    return Result(ids=[eid], goal_id=goal["id"], gnum=goal["gnum"])


def _release(conn, params, now) -> Result:
    goal = _goal(conn, params["goal"])
    version = _version_of(conn, goal, params)
    if goal["status"] != "active":
        raise ActionError(t("err.not_active", gnum=goal["gnum"]))
    when = _when(params, now)
    text = _summary({"done_what": params.get("text")}, "done_what")
    eid = _insert_entry(conn, goal, kind="release", stage=None, text=text, params=params, when=when, now=now, version=version)
    _bump_version(conn, goal, version, when, eid, params.get("occurred_at") not in (None, ""))
    return Result(ids=[eid], goal_id=goal["id"], gnum=goal["gnum"])


def _stage_start(conn, params, now) -> Result:
    goal = _goal(conn, params["goal"])
    st = _stage(params, True)
    if points.is_point(goal):
        raise ActionError(t("err.point_no_stage", gnum=goal["gnum"]))
    if goal["status"] != "active":
        raise ActionError(t("err.stage_on_done" if goal["status"] == "done" else "err.stage_on_abandoned", gnum=goal["gnum"]))
    when = _when(params, now)
    opened = open_stages(conn, goal["id"])
    if st in opened:
        raise ActionError(t("err.stage_open", gnum=goal["gnum"], stage=st, since=local_text(opened[st])))
    text = str(params.get("text") or "").strip() or t("text.stage_start", stage=st)
    eid = _insert_entry(conn, goal, kind="stage_start", stage=st, text=text, params=params, when=when, now=now)
    return Result(ids=[eid], goal_id=goal["id"], gnum=goal["gnum"])


def _stage_end(conn, params, now) -> Result:
    goal = _goal(conn, params["goal"])
    st = _stage(params, True)
    when = _when(params, now)
    opened = open_stages(conn, goal["id"])
    if st not in opened:
        raise ActionError(t("err.stage_not_open", gnum=goal["gnum"], stage=st))
    if when < opened[st]:
        raise ActionError(t("err.end_before_start"))
    text = str(params.get("text") or "").strip() or t("text.stage_end", stage=st)
    eid = _insert_entry(conn, goal, kind="stage_end", stage=st, text=text, params=params, when=when, now=now)
    return Result(ids=[eid], goal_id=goal["id"], gnum=goal["gnum"])


def _complete(conn, params, now) -> Result:
    goal = _goal(conn, params["goal"])
    if points.is_point(goal):
        raise ActionError(t("err.point_complete", gnum=goal["gnum"]))
    if goal["status"] == "done":
        raise ActionError(t("err.already_done", gnum=goal["gnum"]))
    done_what = _summary(params, "done_what")
    when = _when(params, now)
    ids = []
    for st, started in open_stages(conn, goal["id"]).items():
        if when < started:
            raise ActionError(t("err.complete_before_stage", stage=st))
        ids.append(_insert_entry(conn, goal, kind="stage_end", stage=st, text=t("text.stage_end_complete", stage=st),
                                 params=params, when=when, now=now))
    text = str(params.get("text") or "").strip() or t("text.complete")
    ids.append(_insert_entry(conn, goal, kind="complete", stage=None, text=text, params=params, when=when, now=now))
    conn.execute("UPDATE goals SET status='done', done_at=?, updated_at=? WHERE id=?", (iso(when), iso(now), goal["id"]))
    if done_what:   # left alone when empty: re-opening and completing again keeps the text written the first time
        conn.execute("UPDATE goals SET done_what=? WHERE id=?", (done_what, goal["id"]))
    return Result(ids=ids, goal_id=goal["id"], gnum=goal["gnum"])


def _todo_add(conn, params, now) -> Result:
    gid = _goal(conn, params["goal"])["id"] if params.get("goal") else None
    cur = conn.execute("INSERT INTO todos(goal_id, text, created_at) VALUES(?,?,?)",
                       (gid, str(params["text"]).strip(), iso(now)))
    return Result(ids=[int(cur.lastrowid)], goal_id=gid)


def _todo_done(conn, params, now) -> Result:
    tid = _int(params, "todo_id")
    if conn.execute("UPDATE todos SET done_at=? WHERE id=? AND done_at IS NULL", (iso(now), tid)).rowcount != 1:
        raise ActionError(t("err.todo", id=tid))
    return Result(ids=[tid])


def _note_add(conn, params, now) -> Result:
    gid = _goal(conn, params["goal"])["id"] if params.get("goal") else None
    cur = conn.execute("INSERT INTO notes(text, goal_id, created_at) VALUES(?,?,?)",
                       (str(params["text"]).strip(), gid, iso(now)))
    return Result(ids=[int(cur.lastrowid)], goal_id=gid)


def _note_resolve(conn, params, now) -> Result:
    nid = _int(params, "note_id")
    if conn.execute("UPDATE notes SET resolved_at=?, summary=? WHERE id=? AND resolved_at IS NULL",
                    (iso(now), str(params["summary"]).strip(), nid)).rowcount != 1:
        raise ActionError(t("err.note", id=nid))
    return Result(ids=[nid])


def _sync_mark(conn, params, now) -> Result:
    status = params["status"]
    if status not in ("pushed", "skip"):
        raise ActionError(t("err.bad_sync_status"))
    raw = params["entry_ids"]
    try:
        ids = [int(str(x).strip()) for x in (raw if isinstance(raw, list) else str(raw).replace("，", ",").split(","))
               if str(x).strip()]
    except ValueError:
        raise ActionError(t("err.bad_entry_ids", value=repr(raw))) from None
    for eid in ids:
        if conn.execute("UPDATE entries SET sync=?, synced_at=?, team_ref=? WHERE id=? AND sync='pending'",
                        (status, iso(now), str(params.get("team_ref") or ""), eid)).rowcount != 1:
            raise ActionError(t("err.not_pending", id=eid))
    return Result(ids=ids)


def _void(conn, params, now) -> Result:
    eid = _int(params, "entry_id")
    if conn.execute("UPDATE entries SET voided_at=?, void_reason=? WHERE id=? AND voided_at IS NULL",
                    (iso(now), str(params["reason"]).strip(), eid)).rowcount != 1:
        raise ActionError(t("err.void", id=eid))
    e = conn.execute("SELECT goal_id, kind FROM entries WHERE id=?", (eid,)).fetchone()
    if e["kind"] == "point_done":  # a one-off ticked by mistake goes back to "not done" (a monthly one is active anyway)
        conn.execute("UPDATE goals SET status='active', done_at=NULL, updated_at=? WHERE id=? AND status='done'"
                     " AND point_repeat IS NULL", (iso(now), e["goal_id"]))
    return Result(ids=[eid])


def _point_rule(params: dict, goal: sqlite3.Row | None) -> tuple[datetime | None, str | None, str | None]:
    """The point-task rule from the parameters; with a goal, anything not given keeps its current value."""
    try:
        zone = points.parse_zone(params["point_zone"]) if "point_zone" in params else (goal["point_zone"] if goal else settings.tz_name())
        repeat = points.parse_repeat(params["repeat"]) if "repeat" in params else (goal["point_repeat"] if goal else None)
        if params.get("point_at") not in (None, ""):
            point_at = points.parse_point_at(params["point_at"], zone)
        elif goal is not None:
            point_at = parse_ts(goal["point_at"])
        else:
            return None, None, None
    except ValueError as e:
        raise ActionError(str(e)) from None
    return point_at, zone, repeat


def _point_done(conn, params, now) -> Result:
    goal = _goal(conn, params["goal"])
    if not points.is_point(goal):
        raise ActionError(t("err.not_point_done", gnum=goal["gnum"]))
    if goal["status"] == "abandoned":
        raise ActionError(t("err.point_cancelled", gnum=goal["gnum"]))
    when = _when(params, now)
    ents = conn.execute("SELECT * FROM entries WHERE goal_id=? AND voided_at IS NULL", (goal["id"],)).fetchall()
    done = points.done_map(ents)
    raw = params.get("occurrence")
    if raw not in (None, ""):
        try:
            want = points.parse_point_at(raw, goal["point_zone"])
        except ValueError as e:
            raise ActionError(str(e).replace("point_at", "occurrence")) from None
        allowed = {iso(moment): moment for moment in points.occurrences(goal, want + timedelta(seconds=1))}
        if iso(want) not in allowed:
            raise ActionError(t("err.no_occurrence", gnum=goal["gnum"], at=points.zone_text(want, goal["point_zone"]),
                                rule=points.rule_text(goal)))
        moment = want
    else:
        undone = [m for m in points.occurrences(goal, when + points.EARLY_LIMIT) if iso(m) not in done]
        if not undone:
            raise ActionError(t("err.none_within", gnum=goal["gnum"], rule=points.rule_text(goal)))
        moment = undone[0]
    if iso(moment) in done:
        raise ActionError(t("err.already_ticked", at=points.zone_text(moment, goal["point_zone"]), id=done[iso(moment)]["id"]))
    text = str(params.get("text") or "").strip() or t("text.point_done", title=goal["title"],
                                                      at=points.short_text(moment, goal["point_zone"]))
    try:
        eid = _insert_entry(conn, goal, kind="point_done", stage=None, text=text, params=params, when=when, now=now,
                            occurrence=iso(moment))
    except sqlite3.IntegrityError:  # two conversations tick the same occurrence at once: the unique index catches it
        raise ActionError(t("err.just_ticked", at=points.zone_text(moment, goal["point_zone"]))) from None
    if goal["point_repeat"] is None:  # a one-off is complete once ticked and leaves "in progress"
        conn.execute("UPDATE goals SET status='done', done_at=?, updated_at=? WHERE id=?", (iso(when), iso(now), goal["id"]))
    return Result(ids=[eid], goal_id=goal["id"], gnum=goal["gnum"])


def _point_reminded(conn, params, now) -> Result:
    set_meta(conn, "points_reminded_day", local_day(now).isoformat())  # by local date: remind once a day
    return Result()


_HANDLERS = {
    "goal_create": _goal_create, "goal_update": _goal_update, "log": _log, "stage_start": _stage_start,
    "stage_end": _stage_end, "complete": _complete, "todo_add": _todo_add, "todo_done": _todo_done,
    "note_add": _note_add, "note_resolve": _note_resolve, "sync_mark": _sync_mark, "void": _void,
    "point_done": _point_done, "point_reminded": _point_reminded, "release": _release,
}
