"""The read model: the page and the MCP server both read from here, so they never compute things twice.

The core rule: the rows of the timeline are decided by the window. A goal in progress is always there; a
finished one appears only while the window touches the time it was active. What is done drifts out of
view with time and comes back when you drag back to it — the board neither bloats nor loses anything.
"""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app import points, settings
from app.i18n import every, t, weekday
from app.model import (VERSION, day_bounds, gnum_key, is_default_abandon, iso, kind_label, local_day, local_text, parse_ts,
                       sync_label, utc_now, version_key, zoned)
from app.store import find_goal, get_meta
from app.team import strip_marked


def _entries(conn: sqlite3.Connection, where: str = "", args: tuple = ()) -> list[sqlite3.Row]:
    return list(conn.execute(f"SELECT * FROM entries WHERE voided_at IS NULL {where} ORDER BY occurred_at, id", args))


def spans_of(entries: list[sqlite3.Row]) -> list[dict]:
    """Replay stage_start / stage_end in order of occurrence into the spans of each stage; an open span has end=None."""
    opened: dict[str, datetime] = {}
    spans: list[dict] = []
    for e in entries:
        if e["kind"] == "stage_start":
            opened[e["stage"]] = parse_ts(e["occurred_at"])
        elif e["kind"] == "stage_end" and e["stage"] in opened:
            spans.append({"stage": e["stage"], "start": opened.pop(e["stage"]), "end": parse_ts(e["occurred_at"])})
    for st, start in opened.items():
        spans.append({"stage": st, "start": start, "end": None})
    spans.sort(key=lambda s: s["start"])
    return spans


def _goal_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Rows in tree order: a parent, then all of its blocks (recursively). Lines are the first level of grouping.

    - Blocks under the same parent sort by number (G numbers first, G2.9 before G2.10; birth numbers not yet
      pushed after the G numbers, numerically). A newly split block therefore lands inside its parent's area
      on its own. Sorting by creation time would be wrong: a block created here first and pushed later gets a
      higher number than one created on the team board in between.
    - Top level within a line: goals with a birth number sort by birth number whether pushed or not — the
      order you created them in, which never changes, so a row does not jump when it is pushed. Goals created
      directly on the team board (no birth number) come first, by G number.
    - Long-running rows (ongoing upkeep) sink to the bottom of their line: they are always open and would
      otherwise split up the goals that have a beginning and an end.
    """
    rows = list(conn.execute("SELECT * FROM goals"))
    known = {g["gnum"] for g in rows}
    kids: dict[str | None, list[sqlite3.Row]] = defaultdict(list)
    for g in rows:
        kids[g["parent_gnum"] if g["parent_gnum"] in known else None].append(g)
    out: list[sqlite3.Row] = []
    by_gnum = lambda g: (gnum_key(g["gnum"] or ""), parse_ts(g["created_at"]))  # noqa: E731

    def by_top(g: sqlite3.Row) -> tuple:
        b = g["birth"] or ""
        own = (1, b[:1], int(b[1:])) if b[1:].isdigit() else (0, "", 0)
        return (bool(g["long_term"]), own, by_gnum(g))

    def walk(parent: str | None, depth: int = 0) -> None:
        for g in sorted(kids[parent], key=by_gnum if parent is not None else by_top):
            out.append(g)
            if depth < 8:
                walk(g["gnum"], depth + 1)

    walk(None)
    return sorted(out, key=lambda g: settings.line_index(g["line"]))  # stable: tree order within a line; a block on another line goes to its own line


def _line_views(goals) -> list[dict]:
    return settings.line_views(sorted({g["line"] for g in goals if not settings.is_line(g["line"])}))


def _stage_colors(conn: sqlite3.Connection) -> dict[str, str]:
    """The legend: the configured stages, then any stage name the data uses that the config does not have."""
    colors = settings.stage_colors()
    for r in conn.execute("SELECT DISTINCT stage FROM entries WHERE stage IS NOT NULL AND stage<>'' ORDER BY stage"):
        colors.setdefault(r["stage"], settings.stage_color(r["stage"]))
    return colors


def stage_state(spans: list[dict], stage: str | None, at: datetime) -> str:
    """Whether the stage span an entry belongs to is "in progress" or "ended HH:MM" now."""
    if not stage:
        return ""
    for sp in spans:
        if sp["stage"] == stage and sp["start"] <= at and (sp["end"] is None or at <= sp["end"]):
            return t("stage.open") if sp["end"] is None else t("stage.ended", at=local_text(sp["end"]))
    later = [sp for sp in spans if sp["stage"] == stage and sp["start"] > at]
    return "" if not later else (t("stage.open") if later[-1]["end"] is None else t("stage.ended", at=local_text(later[-1]["end"])))


def entry_dict(e: sqlite3.Row, goal: sqlite3.Row | None = None, spans: list[dict] | None = None) -> dict:
    at = parse_ts(e["occurred_at"])
    d = {"id": e["id"], "at": iso(at), "at_local": local_text(at), "hour": at.astimezone(settings.tz()).strftime("%H"),
         "kind": e["kind"], "kind_label": kind_label(e["kind"]),
         "stage": e["stage"], "stage_label": e["stage"] or t("stage.none"),
         "stage_color": settings.stage_color(e["stage"]) if e["stage"] else "",
         "stage_state": stage_state(spans, e["stage"], at) if spans is not None else "",
         "text": e["text"], "task": e["task"], "tool": e["tool"],
         "sync": e["sync"], "sync_label": sync_label(e["sync"]),
         "synced_at": local_text(parse_ts(e["synced_at"])) if e["synced_at"] else "",
         "team_ref": e["team_ref"], "backfilled": (parse_ts(e["recorded_at"]) - at) > timedelta(hours=1),
         "occurrence": e["occurrence"], "version": e["version"]}
    if goal is not None:
        # The summary travels with the entry: a create / complete / edit push at wrap-up takes the current text from here.
        d.update({"gnum": goal["gnum"], "birth": goal["birth"], "goal_title": goal["title"], "line": goal["line"],
                  "goal_what": goal["what"] or "", "goal_done_what": goal["done_what"] or ""})
    return d


def goal_card(conn: sqlite3.Connection, g: sqlite3.Row, now: datetime) -> dict:
    ents = _entries(conn, "AND goal_id=?", (g["id"],))
    spans = spans_of(ents)
    last = ents[-1] if ents else None
    return {"id": g["id"], "gnum": g["gnum"], "birth": g["birth"], "title": g["title"], "line": g["line"], "owner": g["owner"],
            "parent_gnum": g["parent_gnum"], "status": g["status"], "next_step": g["next_step"],
            "blocker": g["blocker"], "version_name": g["version_name"], "source": g["source"],
            "long_term": bool(g["long_term"]), "due": g["due"], "baseline_due": g["baseline_due"],
            "what": g["what"] or "", "done_what": g["done_what"] or "",
            "created_at_local": local_text(parse_ts(g["created_at"])),
            "done_at_local": local_text(parse_ts(g["done_at"])) if g["done_at"] else "",
            "open_stages": [s["stage"] for s in spans if s["end"] is None],
            "has_stages": bool(spans),
            "last_entry_at": local_text(parse_ts(last["occurred_at"])) if last else "",
            "last_entry_text": last["text"] if last else "",
            "pending": conn.execute("SELECT COUNT(*) FROM entries WHERE goal_id=? AND sync='pending' AND voided_at IS NULL",
                                    (g["id"],)).fetchone()[0],
            "point": point_summary(g, ents, now) if points.is_point(g) else None}


def point_summary(g: sqlite3.Row, ents: list[sqlite3.Row], now: datetime) -> dict:
    """A point task at a glance: its rule, the next occurrence, the overdue ones (for the AI and the left column)."""
    occ = points.occurrence_views(g, ents, now, max(now + timedelta(days=62), parse_ts(g["point_at"]) + timedelta(seconds=1)))
    nxt = next((o for o in occ if o["state"] == "upcoming"), None)
    return {"rule": points.rule_text(g), "zone": g["point_zone"], "repeat": g["point_repeat"],
            "next": nxt["text"] if nxt else "", "next_label": nxt["label"] if nxt else "",
            "overdue": [o["text"] for o in occ if o["state"] == "overdue"]}


def points_due(conn: sqlite3.Connection, now: datetime) -> dict:
    """For the reminder when work starts: one line per point task due today (local date) or overdue and not done.
    reminded_today = a conversation already reminded today (set by point_reminded), so the others stay quiet."""
    today = local_day(now)
    _, day_end = day_bounds(today)
    items = []
    for g in conn.execute("SELECT * FROM goals WHERE point_at IS NOT NULL AND status='active'").fetchall():
        for o in points.occurrence_views(g, _entries(conn, "AND goal_id=?", (g["id"],)), now, day_end):
            moment = parse_ts(o["at"])
            if o["state"] == "overdue" and local_day(moment) != today:
                late = points.late_text(o["late_s"]) or t("late.under_hour")
                status, say = t("due.overdue", late=late), t("due.overdue_say", title=g["title"], when=o["text"], late=late)
            elif o["state"] in ("overdue", "upcoming") and local_day(moment) == today:
                status, say = t("due.today"), t("due.today_say", title=g["title"], when=o["text"])
            else:
                continue
            items.append({"gnum": g["gnum"], "title": g["title"], "occurrence": o["at"], "when": o["text"],
                          "status": status, "say": say})
    return {"items": items, "reminded_today": get_meta(conn, "points_reminded_day") == today.isoformat()}


def header(conn: sqlite3.Connection, now: datetime, mode: str = "") -> dict:
    team = settings.team_enabled()
    pulled_text, error = "", ""
    if team and not (get_meta(conn, "demo") or get_meta(conn, "case")):
        # With no team board configured the header says nothing about it at all; the same on demo data and
        # case packs, which are never pulled into.
        pulled = get_meta(conn, "team_pulled_at")
        if pulled:
            mins = int((now - parse_ts(pulled)).total_seconds() // 60)
            pulled_text = t("head.pulled_ago", mins=mins) if mins < 180 else t("head.pulled_at", at=local_text(parse_ts(pulled)))
        else:
            pulled_text = t("head.never_pulled")
        error = get_meta(conn, "team_pull_error") or ""
    zs = settings.zones()
    me = settings.person()
    return {"version": VERSION, "mode": mode, "practice": mode == "practice",
            "person": get_meta(conn, "person") or me["id"], "person_name": me["name"],
            "demo": bool(get_meta(conn, "demo")),   # seeded with the fictional demo board (app/seed.py)
            "case": get_meta(conn, "case") or "",    # loaded from a case pack: says whose board this is a copy of (app/case.py)
            "now_local": now.astimezone(settings.tz()).strftime("%m-%d %H:%M"),
            "clock": " · ".join(f"{z['label']} {now.astimezone(ZoneInfo(z['name'])):%m-%d %H:%M}" for z in zs),
            "today": local_day(now).isoformat(),
            "pending_count": conn.execute("SELECT COUNT(*) FROM entries WHERE sync='pending' AND voided_at IS NULL").fetchone()[0],
            "team_board": team, "team_pulled": pulled_text, "team_pull_error": error}


def state(conn: sqlite3.Connection, day: date, now: datetime | None = None, mode: str = "") -> dict:
    now = now or utc_now()
    start, end = day_bounds(day)
    goals = _goal_rows(conn)
    lines = _line_views(goals)
    names = [ln["name"] for ln in lines]
    by_id = {g["id"]: g for g in goals}
    by_line: dict[str, list[dict]] = {ln: [] for ln in names}
    for g in goals:
        if g["status"] == "active":
            by_line[g["line"]].append(goal_card(conn, g, now))
    spans_cache: dict[int, list[dict]] = {}

    def spans_for(gid: int) -> list[dict]:
        if gid not in spans_cache:
            spans_cache[gid] = spans_of(_entries(conn, "AND goal_id=?", (gid,)))
        return spans_cache[gid]
    day_entries = [entry_dict(e, by_id[e["goal_id"]], spans_for(e["goal_id"])) for e in
                   _entries(conn, "AND occurred_at>=? AND occurred_at<?", (iso(start), iso(end)))]
    hours: dict[str, list[dict]] = defaultdict(list)
    for d in day_entries:
        hours[d["hour"]].append(d)
    # The 7-day strip is centred on the selected day (3 before, 3 after) and never runs past today; with today
    # selected it is the 6 days before. So a past day still has later days to click and a way back to today.
    week = []
    last = min(day + timedelta(days=3), max(local_day(now), day))  # a future day selected (to look at plans) stays on the strip
    for i in range(6, -1, -1):
        d = last - timedelta(days=i)
        s, e = day_bounds(d)
        counts = defaultdict(int)
        for r in conn.execute("SELECT g.line AS line, COUNT(*) AS n FROM entries e JOIN goals g ON g.id=e.goal_id "
                              "WHERE e.voided_at IS NULL AND e.occurred_at>=? AND e.occurred_at<? GROUP BY g.line",
                              (iso(s), iso(e))):
            counts[r["line"]] = r["n"]
        week.append({"day": d.isoformat(), "label": d.strftime("%m-%d"), "weekday": weekday(d.weekday()),
                     "counts": [counts.get(ln, 0) for ln in names], "total": sum(counts.values())})
    todos = [dict(r) | {"gnum": by_id[r["goal_id"]]["gnum"] if r["goal_id"] else "",
                        "created_local": local_text(parse_ts(r["created_at"])),
                        "done_local": local_text(parse_ts(r["done_at"])) if r["done_at"] else ""}
             for r in conn.execute("SELECT * FROM todos WHERE done_at IS NULL OR done_at>=? ORDER BY done_at IS NOT NULL, id DESC",
                                   (iso(now - timedelta(days=3)),))]
    notes = [dict(r) | {"gnum": by_id[r["goal_id"]]["gnum"] if r["goal_id"] else "",
                        "created_local": local_text(parse_ts(r["created_at"])),
                        "resolved_local": local_text(parse_ts(r["resolved_at"])) if r["resolved_at"] else ""}
             for r in conn.execute("SELECT * FROM notes ORDER BY resolved_at IS NOT NULL, id DESC LIMIT 30")]
    return {"header": header(conn, now, mode),
            "day": {"iso": day.isoformat(), "label": t("day.label", md=f"{day:%m-%d}", wd=weekday(day.weekday())),
                    "is_today": day == local_day(now)},
            "lines": [ln | {"goals": by_line[ln["name"]]} for ln in lines],
            "hours": [{"hour": h, "entries": hours[h]} for h in sorted(hours)],
            "entry_count": len(day_entries), "week": week, "todos": todos, "notes": notes,
            "points_due": points_due(conn, now), "stage_colors": _stage_colors(conn)}


def timeline(conn: sqlite3.Connection, start: datetime, end: datetime, now: datetime | None = None) -> dict:
    """The rows that belong in the window [start, end): goals in progress created before the window ends,
    plus goals with a stage span or an entry inside the window."""
    now = now or utc_now()
    rows = []
    goals = _goal_rows(conn)
    for g in goals:
        ents = _entries(conn, "AND goal_id=?", (g["id"],))
        if points.is_point(g):
            # Point tasks do not follow "in progress is always there": a row appears only when the window covers one
            # of its occurrences (an overdue one covers from its moment up to now).
            occ = [o for o in points.occurrence_views(g, ents, now, end) if points.visible(o, start, end)]
            if occ:
                rows.append(_row_base(g) | {"spans": [], "has_stages": False, "dots": [],
                                            "point": {"rule": points.rule_text(g), "occ": occ}})
            continue
        spans = spans_of(ents)
        in_window = any((s["end"] or now) > start and s["start"] < end for s in spans) or \
            any(start <= parse_ts(e["occurred_at"]) < end for e in ents)
        if not spans:  # a goal without stages is drawn as a grey "created → done" bar; touching it counts (same as timeline.js)
            g_end = parse_ts(g["done_at"]) if g["done_at"] else now
            in_window = in_window or (parse_ts(g["created_at"]) < end and g_end > start)
        # In progress is always there — except on days before the goal was created (same as timeline.js).
        started = parse_ts(g["created_at"]) < end
        if not in_window and not (g["status"] == "active" and started):
            continue
        dots = [entry_dict(e) for e in ents if e["kind"] not in ("stage_start", "stage_end")
                and start - timedelta(days=1) <= parse_ts(e["occurred_at"]) < end + timedelta(days=1)]
        rows.append(_row_base(g) | {
            "spans": [{"stage": s["stage"], "color": settings.stage_color(s["stage"]),
                       "start": iso(s["start"]), "end": iso(s["end"]) if s["end"] else None} for s in spans],
            "has_stages": bool(spans), "dots": dots, "point": None})
    return {"start": iso(start), "end": iso(end), "now": iso(now), "rows": rows,
            "lines": [{"name": ln["name"], "mark": ln["mark"], "color": ln["color"]} for ln in _line_views(goals)]}


def _unpause(blocker: str) -> str:
    """"Paused: waiting on X" → "waiting on X" for the row's pause badge (whichever language wrote the prefix)."""
    for prefix in every("team.paused", kind=""):
        if blocker.startswith(prefix):
            return blocker[len(prefix):]
    return blocker


def _row_base(g: sqlite3.Row) -> dict:
    return {"id": g["id"], "gnum": g["gnum"], "birth": g["birth"], "title": g["title"], "line": g["line"],
            "parent_gnum": g["parent_gnum"], "status": g["status"], "next_step": g["next_step"],
            "blocker": g["blocker"], "blocker_short": _unpause(g["blocker"] or ""), "version_name": g["version_name"], "long_term": bool(g["long_term"]), "due": g["due"],
            "baseline_due": g["baseline_due"],   # delay is measured from the first plan ever set
            "created_at": iso(parse_ts(g["created_at"])),
            "done_at": iso(parse_ts(g["done_at"])) if g["done_at"] else None,
            "done_at_local": local_text(parse_ts(g["done_at"]), "%m-%d") if g["done_at"] else ""}


def goal_detail(conn: sqlite3.Connection, key: str, now: datetime | None = None) -> dict:
    now = now or utc_now()
    g = find_goal(conn, key)   # display number, birth number (still found after the push) or internal id
    if g is None:
        raise KeyError(key)
    card = goal_card(conn, g, now)
    ents = _entries(conn, "AND goal_id=?", (g["id"],))
    spans = spans_of(ents)
    days: dict[str, list[dict]] = defaultdict(list)
    for e in reversed(ents):
        d = entry_dict(e, None, spans)
        at = parse_ts(e["occurred_at"]).astimezone(settings.tz())
        days[t("day.label", md=f"{at:%m-%d}", wd=weekday(at.weekday()))].append(d)
    stage_rows = []
    for s in spans:
        hrs = ((s["end"] or now) - s["start"]).total_seconds() / 3600
        stage_rows.append({"stage": s["stage"], "color": settings.stage_color(s["stage"]), "start_local": local_text(s["start"]),
                           "end_local": local_text(s["end"]) if s["end"] else t("stage.open"), "hours": round(hrs, 1)})
    parent = conn.execute("SELECT gnum, birth, title FROM goals WHERE gnum=?", (g["parent_gnum"],)).fetchone() if g["parent_gnum"] else None
    # Blocks sort by number, like the timeline; by id would be the order they were entered here.
    children = sorted((dict(r) for r in conn.execute("SELECT gnum, birth, title, status FROM goals WHERE parent_gnum=?", (g["gnum"],))),
                      key=lambda c: gnum_key(c["gnum"] or ""))
    todos = [dict(r) for r in conn.execute("SELECT * FROM todos WHERE goal_id=? ORDER BY done_at IS NOT NULL, id DESC", (g["id"],))]
    tasks = sorted({(e["task"], e["tool"]) for e in ents if e["task"]})
    point = None
    if points.is_point(g):  # every occurrence and whether it was done: all past ones, then the next two
        occ = points.occurrence_views(g, ents, now, max(now + timedelta(days=62), parse_ts(g["point_at"]) + timedelta(seconds=1)))
        ahead = [o for o in occ if o["state"] == "upcoming"][:2]
        rows_ = [o for o in occ if o["state"] != "upcoming"] + ahead
        main = settings.zones()[0]
        for o in rows_:
            late = points.late_text(o["late_s"])
            if o["state"] == "done":
                o["state_text"] = t("occ.done", at=zoned(parse_ts(o["done_at"]), main)) + (t("occ.done_late", late=late) if late else "")
            elif o["state"] == "overdue":
                o["state_text"] = t("occ.overdue", late=late or t("late.under_hour"))
            else:
                o["state_text"] = t(f"occ.{o['state']}")
        point = {"rule": points.rule_text(g), "occ": rows_}
    # Changelog of a long-running row: every closed version (release) and every digest that carries a version.
    releases = [{"version": e["version"], "at_local": zoned(parse_ts(e["occurred_at"]), settings.zones()[0]), "text": e["text"], "kind": e["kind"]}
                for e in reversed(ents) if e["version"]]
    # Highest version first, consistent with the badge; versions without a number go last, equal ones newest first.
    releases.sort(key=lambda r: (version_key(r["version"]) is not None, version_key(r["version"]) or ()), reverse=True)
    # An abandoned goal shows why (the reason of its last "abandon" entry), in the place of "what was done".
    abandon = next((e["text"] for e in reversed(ents) if e["kind"] == "abandon"), "") if g["status"] == "abandoned" else ""
    abandon = strip_marked(abandon)   # an entry backfilled by a pull: keep only the reason
    if is_default_abandon(abandon):   # the placeholder written when no reason was given is not a reason; empty hides the field
        abandon = ""
    return {"goal": card, "line_mark": list(settings.line_mark(g["line"])), "stages": stage_rows, "point": point,
            "releases": releases, "abandon_reason": abandon,
            "days": [{"day": k, "entries": v} for k, v in days.items()],
            "parent": dict(parent) if parent else None, "children": children, "todos": todos,
            "tasks": [{"task": task, "tool": tool} for task, tool in tasks], "header": header(conn, now)}


def pending_entries(conn: sqlite3.Connection) -> list[dict]:
    """Every unpushed entry (across days): the list the AI shows the human for a nod at wrap-up."""
    goals = {g["id"]: g for g in conn.execute("SELECT * FROM goals")}
    cache: dict[int, list[dict]] = {}
    out = []
    for e in _entries(conn, "AND sync='pending'"):
        if e["goal_id"] not in cache:
            cache[e["goal_id"]] = spans_of(_entries(conn, "AND goal_id=?", (e["goal_id"],)))
        out.append(entry_dict(e, goals[e["goal_id"]], cache[e["goal_id"]]))
    return out


def day_counts(conn: sqlite3.Connection, d_from: date, d_to: date) -> dict:
    """For the calendar popover: entries per day in [d_from, d_to] (local days, voided ones excluded); days without entries are absent."""
    if d_to < d_from or (d_to - d_from).days > 93:
        raise ValueError(t("err.day_range"))
    start, _ = day_bounds(d_from)
    _, end = day_bounds(d_to)
    counts: dict[str, int] = defaultdict(int)
    for r in conn.execute("SELECT occurred_at FROM entries WHERE voided_at IS NULL AND occurred_at>=? AND occurred_at<?",
                          (iso(start), iso(end))):
        counts[local_day(parse_ts(r["occurred_at"])).isoformat()] += 1
    return {"from": d_from.isoformat(), "to": d_to.isoformat(), "today": local_day(utc_now()).isoformat(), "counts": dict(counts)}
