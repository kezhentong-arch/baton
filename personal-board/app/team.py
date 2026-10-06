"""Pull my goals from the team board (read-only).

Optional: with no `team_board.base_url` in the config this module is never called and the personal board
works entirely on its own. Pushing back is not done here either — at wrap-up the AI pushes the unpushed
entries through the team board's own MCP after the human nods.

Assumed interface (one request):

    GET {base_url}/api/board/state
    Authorization: Bearer <token>        (omitted when no token is configured)
    → {"goals": [{"id", "gnum", "title", "line", "status", "owner", "parent_id", ...}]}

Field notes are next to where each field is read in `pull`.
"""
from __future__ import annotations

import json
import sqlite3
import urllib.error
import urllib.request
from datetime import datetime

from app import settings
from app.actions import open_stages
from app.i18n import every, t
from app.model import VERSION, iso
from app.store import get_meta, set_meta

# The team board may answer with a status key or with its label in either interface language.
STATUS: dict[str, str] = {"active": "active", "done": "done", "abandoned": "abandoned"}
for _key in ("active", "done", "abandoned"):
    for _label in every(f"team.status.{_key}"):
        STATUS[_label] = _key


def fetch_state(base: str, token: str = "") -> dict:
    base = base.rstrip("/")
    if not base.startswith(("http://", "https://")):
        raise RuntimeError(t("team.bad_url"))
    # A custom User-Agent: some proxies reject urllib's default one outright.
    headers = {"User-Agent": f"personal-board/{VERSION}", "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(f"{base}/api/board/state", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        raise RuntimeError(t("team.http", code=e.code, body=e.read()[:200].decode("utf-8", "replace"))) from None
    except urllib.error.URLError as e:
        raise RuntimeError(t("team.unreachable", base=base, reason=e.reason)) from None
    except (TimeoutError, OSError) as e:  # read timeouts and the like
        raise RuntimeError(t("team.read_error", error=e)) from None
    try:
        payload = json.loads(raw)
    except ValueError:
        raise RuntimeError(t("team.not_json", head=repr(raw[:120]))) from None
    if not isinstance(payload, dict) or "goals" not in payload:
        raise RuntimeError(t("team.no_goals"))
    return payload


def _is_mine(g: dict) -> bool:
    """The team board names a goal's owner by display name (`owner`) and may add `owner_id`; either may match
    my id or name, or the alias in `team_board.owner`."""
    me = settings.person()
    names = {me["id"], me["name"], settings.team_board().get("owner") or me["name"]}
    return g.get("owner") in names or (g.get("owner_id") not in (None, "") and g.get("owner_id") in names)


def _team_map(items: list[dict]) -> dict[str, str]:
    """Name on the team board → local name. A line or stage may set `team_name` when the two differ."""
    return {it.get("team_name") or it["name"]: it["name"] for it in items}


def _span_times(g: dict, stage: str) -> tuple[str, str]:
    """Start and end of the latest span of a stage as given by the team board (`spans`; empty strings if absent)."""
    spans = [sp for sp in (g.get("spans") or []) if sp.get("stage") == stage]
    if not spans:
        return "", ""
    last = spans[-1]
    return last.get("start") or "", last.get("end") or ""


def _sync_open_stages(conn: sqlite3.Connection, goal_id: int, g: dict, pending: int, now: datetime) -> None:
    """Stages open on the team board are open here too; a stage the team board closed while it is still open
    here — with nothing unpushed locally — is closed. Moments come from the team board's spans; without them
    the pull moment is used and the entry says so. With unpushed local changes nothing is touched (local is
    newer; align after the push)."""
    if pending or g["_status"] != "active":
        return
    remote = set(g.get("current_stages") or [])
    local = open_stages(conn, goal_id)
    for st in remote - set(local):
        start, _ = _span_times(g, st)
        _entry(conn, goal_id, "stage_start",
               t("team.stage_open", stage=st) + ("" if start else t("team.start_at_pull")),
               start or iso(now), now, stage=st)
    for st in set(local) - remote:
        _, end = _span_times(g, st)
        _entry(conn, goal_id, "stage_end", t("team.stage_closed", stage=st) + ("" if end else t("team.at_pull")),
               end or iso(now), now, stage=st)
    for st in remote & set(local):   # a start once guessed from the pull moment is corrected when the real one arrives
        start, _ = _span_times(g, st)
        if start:
            _fix_seed_time(conn, goal_id, "stage_start", st, start, t("team.stage_open", stage=st))


def _fix_seed_time(conn: sqlite3.Connection, goal_id: int, kind: str, stage: str | None, at: str, text: str) -> None:
    """An entry backfilled by a pull could only use the pull moment; once the team board gives the real moment
    that entry is corrected and its "recorded at pull time" remark dropped. Only entries written by a pull are
    touched, never a human's."""
    tasks = every("team.task")
    marks = ",".join("?" * len(tasks))
    conn.execute(f"UPDATE entries SET occurred_at=?, text=? WHERE goal_id=? AND kind=? AND stage IS ? AND tool='seed'"
                 f" AND task IN ({marks}) AND voided_at IS NULL AND occurred_at<>?", (at, text, goal_id, kind, stage, *tasks, at))


def _marked(g: dict) -> str:
    """"Marked Done on the team board"."""
    return t("team.marked", status=t(f"team.status.{g['_status']}"))


def _why(g: dict) -> str:
    """The reason a goal was abandoned on the team board, appended to the backfilled "abandon" entry; the
    detail page's "Why abandoned" reads it from there."""
    reason = (g.get("abandon_reason") or "").strip() if g["_status"] == "abandoned" else ""
    return t("text.reason", reason=reason) if reason else ""


def strip_marked(text: str) -> str:
    """Undo `_marked(...) [+ at-pull remark] + _why(...)`: keep only the reason. Works for either language."""
    for lang in settings.LANGS:
        head = t("team.marked", lang=lang, status=t("team.status.abandoned", lang=lang))
        if text.startswith(head):
            rest = text[len(head):]
            remark = t("team.at_pull", lang=lang)
            if rest.startswith(remark):
                rest = rest[len(remark):]
            sep = t("text.reason", lang=lang, reason="")
            return rest[len(sep):] if rest.startswith(sep) else rest.lstrip("：: ")
    return text


def _entry(conn: sqlite3.Connection, goal_id: int, kind: str, text: str, at: str, now: datetime, stage: str | None = None) -> None:
    """An entry backfilled by a pull: its source is the team board and it is already "pushed" (the fact lives there)."""
    conn.execute("INSERT INTO entries(goal_id, stage, kind, text, task, tool, occurred_at, recorded_at, sync, synced_at)"
                 " VALUES(?,?,?,?,?,?,?,?,?,?)", (goal_id, stage, kind, text, t("team.task"), "seed", at, iso(now), "pushed", iso(now)))


def _backfill_create(conn: sqlite3.Connection, goal_id: int, created_at: str, approved_at: str, now: datetime) -> None:
    """A goal created on the team board gets a "created" entry here too. The moment is the team board's
    `approved_at`; without it, the local row's start. Never duplicated — but an entry once guessed from the
    pull moment is corrected when the real moment arrives."""
    if approved_at:
        _fix_seed_time(conn, goal_id, "goal_create", None, approved_at, t("team.created"))
        conn.execute("UPDATE goals SET created_at=? WHERE id=? AND created_at<>?", (approved_at, goal_id, approved_at))
    if conn.execute("SELECT 1 FROM entries WHERE goal_id=? AND kind='goal_create' AND voided_at IS NULL", (goal_id,)).fetchone():
        return
    _entry(conn, goal_id, "goal_create", t("team.created") if approved_at else t("team.created_guess"),
           approved_at or created_at, now)


def _fail(conn: sqlite3.Connection, msg: str) -> dict:
    with conn:
        set_meta(conn, "team_pull_error", msg)
    return {"ok": False, "error": msg, "pulled": 0}


def pull(conn: sqlite3.Connection, now: datetime) -> dict:
    """Pull the goals I own (and the parents of those). A failure is never swallowed: it is recorded in meta
    and returned as `error`; local goals stay untouched."""
    if not settings.team_enabled():
        return {"ok": False, "error": t("team.off"), "pulled": 0}   # switched off: say so, record nothing
    if get_meta(conn, "demo") or get_meta(conn, "case"):
        # Demo data and case packs are someone else's board: pulling as me would mix my real goals into it and flag
        # theirs as "no longer mine". Reset first.
        # An expected state, not a failed pull: tell the caller, but leave no error in the header.
        return {"ok": False, "error": t("team.demo") if get_meta(conn, "demo") else t("team.case"), "pulled": 0}
    tb = settings.team_board()
    try:
        payload = fetch_state(tb["base_url"], tb["token"])
    except RuntimeError as e:
        return _fail(conn, str(e))
    line_map, stage_map = _team_map(settings.lines()), _team_map(settings.active()["stages"])
    goals = [dict(g) for g in payload.get("goals", []) if not g.get("sample")]   # `sample`: example goals on the team board
    for g in goals:   # translate the team board's names to local ones once, up front
        g["line"] = line_map.get(g.get("line"), g.get("line"))
        g["_status"] = STATUS.get(g.get("status"), "active")
        g["current_stages"] = [stage_map[s] for s in (g.get("current_stages") or []) if s in stage_map]
        g["spans"] = [dict(sp, stage=stage_map[sp["stage"]]) for sp in (g.get("spans") or []) if sp.get("stage") in stage_map]
    by_id = {g["id"]: g for g in goals}
    mine = {g["id"] for g in goals if _is_mine(g)}
    keep = set(mine)
    for gid in mine:  # parents come along so the page can show "G2.2 belongs to G2"
        p = by_id.get(gid, {}).get("parent_id")
        while p and p not in keep and p in by_id:
            keep.add(p)
            p = by_id[p].get("parent_id")
    n = 0
    me = settings.person()["id"]
    try:
        with conn:
            for g in goals:
                if g["id"] not in keep or not settings.is_team_line(g["line"]):
                    continue
                parent = by_id.get(g.get("parent_id") or 0, {}).get("gnum")
                status = g["_status"]
                due = g.get("latest_due") or g.get("baseline_due") or None
                baseline = g.get("baseline_due") or None   # the first plan ever set: delay is measured from it, and the team board is the authority
                owner = me if g["id"] in mine else str(g.get("owner") or "")   # a parent kept for context keeps its owner's name
                approved_at = g.get("approved_at") or ""
                closed_at = g.get("done_at") or g.get("abandoned_at") or ""
                version_name = (g.get("version") or {}).get("name", "") if isinstance(g.get("version"), dict) else ""
                # Goal summary: the team board's `note` is "what", and `done_what` written at completion comes along.
                what, done_what = (g.get("note") or "").strip(), (g.get("done_what") or "").strip()
                paused = t("team.paused", kind=g["paused"]) if g.get("paused") else ""
                row = conn.execute("SELECT * FROM goals WHERE team_id=?", (g["id"],)).fetchone()
                if row is None and g.get("source"):
                    # Created here and pushed: the team board keeps its birth number as `source`, the surest way to
                    # claim the local row — it works even before the display number was switched to the G number.
                    row = conn.execute("SELECT * FROM goals WHERE birth=? AND team_id IS NULL", (g["source"],)).fetchone()
                if row is None:
                    # Created here, pushed and already renamed to its G number: claim that row instead of inserting a
                    # second one that would hit the unique key.
                    row = conn.execute("SELECT * FROM goals WHERE gnum=? AND team_id IS NULL", (g["gnum"],)).fetchone()
                if row is None:
                    cur = conn.execute("INSERT INTO goals(gnum, line, title, owner, parent_gnum, status, source, team_id, long_term, due, baseline_due, blocker, version_name, what, done_what, created_at, updated_at, done_at)"
                                       " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                       (g["gnum"], g["line"], g["title"], owner, parent, status, "team", g["id"],
                                        1 if g.get("long_term") else 0, due, baseline or due, paused,
                                        version_name, what or None, done_what or None, approved_at or iso(now), iso(now),
                                        (closed_at or iso(now)) if status != "active" else None))
                    _backfill_create(conn, int(cur.lastrowid), iso(now), approved_at, now)
                    if status != "active":   # already closed when first pulled: backfill the close too, at the team board's moment
                        _entry(conn, int(cur.lastrowid), "complete" if status == "done" else "abandon",
                               _marked(g) + ("" if closed_at else t("team.at_pull")) + _why(g), closed_at or iso(now), now)
                    _sync_open_stages(conn, int(cur.lastrowid), g, 0, now)
                    n += 1
                    continue
                _backfill_create(conn, row["id"], row["created_at"], approved_at, now)
                if baseline and baseline != row["baseline_due"]:   # regardless of unpushed local changes: the baseline is the team board's
                    conn.execute("UPDATE goals SET baseline_due=? WHERE id=?", (baseline, row["id"]))
                if version_name and version_name != (row["version_name"] or ""):   # the version (milestone) set on the team board is the badge
                    conn.execute("UPDATE goals SET version_name=? WHERE id=?", (version_name, row["id"]))
                pending = conn.execute("SELECT COUNT(*) FROM entries WHERE goal_id=? AND sync='pending' AND voided_at IS NULL",
                                       (row["id"],)).fetchone()[0]
                _sync_open_stages(conn, row["id"], g, pending, now)
                if row["gnum"] != g["gnum"]:   # claimed by source / team id and the display number changed: children follow, or they are orphaned
                    conn.execute("UPDATE goals SET parent_gnum=? WHERE parent_gnum=?", (g["gnum"], row["gnum"]))
                conn.execute("UPDATE goals SET gnum=?, line=?, title=?, parent_gnum=?, long_term=?, source='team', team_id=?, blocker=?, updated_at=? WHERE id=?",
                             (g["gnum"], g["line"], g["title"], parent, 1 if g.get("long_term") else 0, g["id"],
                              paused, iso(now), row["id"]))
                if paused != (row["blocker"] or ""):  # paused / resumed on the team board: leave a note so the entries show it
                    pauses = g.get("pauses") or []     # the moment is the start / end of the team board's latest pause
                    last = pauses[-1] if pauses else {}
                    at = (last.get("start") if paused else last.get("end")) or iso(now)
                    _entry(conn, row["id"], "note", t("team.note_paused", text=paused) if paused else t("team.note_resumed"), at, now)
                if not pending:
                    # Summary: where it differs the team board wins (not while local changes are unpushed, as with the plan
                    # below). Whether a field was sent is judged by its key: absent = leave local alone, empty = it was cleared there.
                    for key, col, val in (("note", "what", what), ("done_what", "done_what", done_what)):
                        if key in g and val != (row[col] or ""):
                            conn.execute(f"UPDATE goals SET {col}=? WHERE id=?", (val or None, row["id"]))
                    # The team board's status / plan overwrite local ones only when nothing local is unpushed.
                    # A plan may carry an hour: if the team board gives one, it wins; if it gives only a date and the local
                    # plan is the same day with an hour, the local hour is kept — only a different day overwrites it.
                    local_due = row["due"] or None
                    timed = bool(due) and len(due) > 10
                    changed = ((due or None) != local_due) if timed else ((due or None) != (local_due[:10] if local_due else None))
                    if changed:
                        _entry(conn, row["id"], "due", t("team.due", new=due or t("team.no_due"), old=local_due or t("team.no_due")), iso(now), now)
                        conn.execute("UPDATE goals SET due=? WHERE id=?", (due, row["id"]))
                    if status != "active" and row["status"] == "active":
                        for st in open_stages(conn, row["id"]):
                            _, end = _span_times(g, st)
                            _entry(conn, row["id"], "stage_end", t("team.marked_stage", marked=_marked(g), stage=st), end or closed_at or iso(now), now, stage=st)
                        _entry(conn, row["id"], "complete" if status == "done" else "abandon",
                               _marked(g) + ("" if closed_at else t("team.at_pull")) + _why(g), closed_at or iso(now), now)
                        conn.execute("UPDATE goals SET status=?, done_at=? WHERE id=?", (status, closed_at or iso(now), row["id"]))
                    elif status != "active" and closed_at:   # a close once guessed from the pull moment is corrected
                        _fix_seed_time(conn, row["id"], "complete" if status == "done" else "abandon", None, closed_at, _marked(g))
                        conn.execute("UPDATE goals SET done_at=? WHERE id=? AND done_at<>?", (closed_at, row["id"], closed_at))
                    elif status == "active" and row["status"] != "active":
                        _entry(conn, row["id"], "note", t("team.reopened"), iso(now), now)
                        conn.execute("UPDATE goals SET status='active', done_at=NULL WHERE id=?", (row["id"],))
                n += 1
            # A goal whose owner changed on the team board (or that was deleted there) is no longer aligned and would
            # pretend to be in progress forever: flag it and leave a note; the human decides what to do with it.
            not_mine = every("team.not_mine")
            for row in conn.execute("SELECT id, team_id, blocker FROM goals WHERE team_id IS NOT NULL AND status='active'").fetchall():
                if row["team_id"] in keep or row["blocker"] in not_mine:
                    continue
                conn.execute("UPDATE goals SET blocker=?, updated_at=? WHERE id=?", (t("team.not_mine"), iso(now), row["id"]))
                _entry(conn, row["id"], "note", t("team.not_mine_note"), iso(now), now)
            set_meta(conn, "team_pulled_at", iso(now))
            set_meta(conn, "team_pull_error", "")
    except sqlite3.Error as e:  # failing to write locally is a failed pull too; the page and the AI must see it
        return _fail(conn, t("team.write_failed", error=e))
    return {"ok": True, "pulled": n, "error": ""}
