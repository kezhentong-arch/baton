"""把状态整理成页面要的数据。只读，不写库。"""
from __future__ import annotations

import re

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from team_board import config
from team_board.board.actions import Who
from team_board.board.github_sync import incomplete, last_success, latest_run, running_since
from team_board.board.issues import GhData, dwell, last_activity, milestone_moves, subcontract_wait
from team_board.board.model import (DEFAULT_ZOOM, SUBCONTRACT_WARN_DAYS, SYNC_STALE_MINUTES, ZOOM_DAYS,
                                    duration_text, gh_due_day, is_team_owner, iso, late_text, lines, pause_kinds,
                                    people, person_name, stages, status_label, tz_day, tz_text, zooms)
from team_board.board.state import (Board, Goal, blamed_children, delay, delay_text, dependency_warnings, fold,
                                    handoffs, is_stale, pause_days, pause_time, stage_days, stage_spans, stage_time)
from team_board.board.store import Event, load_events
from team_board.board.timeline import (LineGroup, build_timeline, version_carriers, version_done_at, version_href,
                                       version_name, weekdays)
from team_board.i18n import t


@dataclass(frozen=True)
class Blocker:
    kind: str                         # 页面上那个小标签的文字
    text: str
    href: str
    goal_id: int | None = None        # 版本的卡点没有目标；按人筛选时只留他目标上的卡点
    key: str = ""                     # 卡点的种类，排序用


_BLOCKER_ORDER = ("late", "dragged", "dep", "pause", "stale", "subcontract", "version")


def _blocker(key: str, text: str, href: str, goal_id: int | None = None) -> Blocker:
    return Blocker(t(f"blk.{key}"), text, href, goal_id, key)


def freshness(conn: sqlite3.Connection, now: datetime) -> dict:
    """GitHub 数据的新鲜度；没开 GitHub 同步时 enabled=False，页面整块不显示。"""
    if not config.current().github.enabled:
        return {"enabled": False, "running": "", "last_ok": "", "stale": False, "last_error": "", "warnings": []}
    last, run, running = last_success(conn), latest_run(conn), running_since(conn)
    return {
        "enabled": True,
        "running": tz_text(running) if running else "",
        "last_ok": tz_text(last) if last else t("sync.never"),
        "stale": last is None or now - last > timedelta(minutes=SYNC_STALE_MINUTES),
        "last_error": run["error"] if run is not None and run["ok"] == 0 else "",
        # 事件没取全的单：读持久表，补齐前一直显示（不随下一轮同步消失）
        "warnings": incomplete(conn),
    }


def _label(g: Goal) -> str:
    return (t("sample.prefix") if g.sample else "") + g.title


def blockers(b: Board, gh: GhData, now: datetime, sample: bool = False, root: str = "/board") -> list[Blocker]:
    """卡点。真实看板只列真实目标；示例看板 = 真实 + 示例，示例标「示例·」。"""
    out: list[Blocker] = []
    for g in b.goals.values():
        href = f"{root}/goal/{g.id}"
        if g.sample and not sample:
            continue
        if g.status in ("done", "abandoned"):
            continue
        late = delay_text(g, now)
        if late:
            ext = pause_time(g, now)["external"]
            out.append(_blocker("late", t("blk.late_text", title=_label(g), late=late)
                                + (t("blk.late_external", ext=duration_text(ext)) if ext else ""), href, g.id))
        blamed = blamed_children(g, b, now)
        if blamed:
            names = t("sep").join(b.goals[c].title for c in blamed)
            out.append(_blocker("dragged", t("blk.dragged_text", title=_label(g), names=names), href, g.id))
        p = g.current_pause
        if p:
            extra = t("blk.pause_waiting", title=b.goals[p.depends_on].title) if p.depends_on in b.goals else ""
            out.append(_blocker("pause", t("blk.pause_text", title=g.title, kind=pause_kinds()[p.kind],
                                           dur=duration_text(now - p.start)) + extra, href, g.id))
        if is_stale(g, last_activity(gh, g.links), now) and g.last_stage_change:
            running = t("sep").join(sp.stage for sp in g.open_spans)
            out.append(_blocker("stale", t("blk.stale_text", title=g.title, stages=running,
                                           dur=duration_text(now - g.last_stage_change)), href, g.id))
        for link in g.links:
            issue = gh.issues.get((link.repo, link.number))
            if link.kind != "subcontract" or issue is None:
                continue
            wait, delivered = subcontract_wait(issue, gh.events.get((link.repo, link.number), []), now)
            if not delivered and wait > timedelta(days=SUBCONTRACT_WARN_DAYS):
                out.append(_blocker("subcontract", t("blk.subcontract_text", title=g.title,
                                                     ref=f"{link.repo.split('/')[1]}#{link.number}",
                                                     dur=duration_text(wait)), href, g.id))
    for gid, _dep, text in dependency_warnings(b, now):
        if b.goals[gid].sample and not sample:
            continue
        out.append(_blocker("dep", t("blk.dep_text", title=_label(b.goals[gid]), text=text), f"{root}/goal/{gid}", gid))
    for ref, vt in b.versions.items():
        repo, num = ref.split("#")
        m = gh.milestones.get((repo, int(num)))
        title = m.title if m else ref
        href = version_href(ref, root)
        if version_done_at(vt, m) is None and vt.baseline:
            late = late_text(vt.baseline.at, now)
            if late:
                out.append(_blocker("version", t("blk.version_text", title=title, late=late), href))
    return sorted(out, key=lambda x: _BLOCKER_ORDER.index(x.key))


def _edited_text(p: dict) -> str:
    parts = {
        "title": lambda: t("hist.edit.title", title=p.get("title")),
        "note": lambda: t("hist.edit.note"),
        "done_what": lambda: t("hist.edit.done_what"),
        "line": lambda: t("hist.edit.line", line=p.get("line", "")),
        "version": lambda: t("hist.edit.version", version=p.get("version") or t("hist.edit.version_none")),
        "parent_id": lambda: t("hist.edit.parent", gnum=f"G{p.get('parent_id')}") if p.get("parent_id") else t("hist.edit.parent_none"),
        "long_term": lambda: t("hist.edit.long_term_on") if p.get("long_term") else t("hist.edit.long_term_off"),
        "source": lambda: t("hist.edit.source", source=p.get("source")),
    }
    return t("hist.edited") + t("hist.sep").join(parts[k]() for k in p if k != "seq")      # seq 是挪到新上层下拿的号，不单独写


# 每种记录在「修改留痕」里怎么写
_KIND_TEXT = {
    "goal.proposed": lambda p: t("hist.proposed", title=p["title"], line=p["line"])
    + (t("hist.proposed_long_term") if p.get("long_term") else "")
    + (t("hist.proposed_version", version=p["version"]) if p.get("version") else "")
    + (t("hist.proposed_source", source=p["source"]) if p.get("source") else ""),
    "goal.approved": lambda p: t("hist.approved", due=p["baseline_due"]) if p.get("baseline_due") else t("hist.approved_no_due"),
    "goal.assigned": lambda p: t("hist.assigned", owner=person_name(p["owner"], p["owner"])),
    "stage.started": lambda p: t("hist.stage_started", stage=p["stage"], who=person_name(p["executor"], p["executor"])),
    "stage.ended": lambda p: t("hist.stage_ended", stage=p["stage"]),
    "goal.edited": _edited_text,
    "dep.removed": lambda p: t("hist.dep_removed", gnum=f"G{p['on_goal']}"),
    "event.voided": lambda p: t("hist.voided", id=p["event_id"], reason=p["reason"]),
    "note.added": lambda p: t("hist.note_added", text=p["text"][:60]),
    "note.resolved": lambda p: t("hist.note_resolved", id=p["note_id"], summary=p["summary"]),
    "pause.started": lambda p: t("hist.paused", kind=pause_kinds().get(p["kind"], p["kind"]))
    + (t("hist.paused_on", gnum=f"G{p['depends_on']}") if p.get("depends_on") else "")
    + (t("hist.paused_note", note=p["note"]) if p.get("note") else ""),
    "pause.ended": lambda p: t("hist.resumed"),
    "due.changed": lambda p: t("hist.due_changed", due=p["due"], reason=p["reason"]),
    "dep.declared": lambda p: t("hist.dep_declared", stage=p["at_stage"], gnum=f"G{p['on_goal']}")
    + (t("hist.dep_need_by", need=p["need_by"]) if p.get("need_by") else ""),
    "issue.linked": lambda p: t("hist.issue_linked_sub" if p["kind"] == "subcontract" else "hist.issue_linked",
                                ref=f"{p['repo']}#{p['number']}"),
    "issue.unlinked": lambda p: t("hist.issue_unlinked", ref=f"{p['repo']}#{p['number']}"),
    "goal.completed": lambda p: t("hist.completed") + (t("hist.completed_what") if p.get("done_what") else ""),
    "goal.abandoned": lambda p: t("hist.abandoned", reason=p["reason"]),
    "version.tracked": lambda p: t("hist.version_tracked"),
    "version.planned": lambda p: t("hist.version_planned", due=p["due"]) + (t("hist.version_prefill") if p.get("source") == "github" else ""),
    "version.completed": lambda p: t("hist.completed"),
}


def describe(e: Event, b: Board | None = None, viewer: str = "", gh: GhData | None = None) -> dict:
    who = people().get(e.actor, e.actor) + {"ai": t("via.ai"), "seed": t("via.seed")}.get(e.via, "")
    voided = b is not None and e.id in b.voided
    text = _KIND_TEXT.get(e.kind, lambda p: e.kind)(e.payload)
    if b is not None:   # 文案里的「G17」换成层级号「G2.1」
        text = re.sub(r"G(\d+)", lambda m: b.goals[int(m[1])].gnum if int(m[1]) in b.goals else m[0], text)
    if gh is not None:  # 留痕里的版本用人话名字（里程碑标题），不用「仓库#编号」
        text = re.sub(r"[\w.-]+/[\w.-]+#\d+", lambda m: t("hist.version_name", name=version_name(m[0], gh)) if m[0] in b.versions or
                      any(x.version == m[0] for x in b.goals.values()) else m[0], text) if b is not None else text
    return {"id": e.id, "when": tz_text(e.occurred_at), "who": who,
            "text": text, "backfill": e.backfill,
            "voided": voided, "void_reason": b.voided[e.id].payload["reason"] if voided else "",
            # 能不能作废：原记录人或 owner 角色；作废记录本身不能再作废
            "can_void": (b is not None and not voided and e.kind != "event.voided"
                         and bool(viewer) and (viewer == e.actor or is_team_owner(viewer)))}


def due_text(g: Goal) -> str:
    """计划完成日的人话：长期负责的事没有完成日，写「长期」而不是「未定」。"""
    if g.latest_due:
        return str(g.latest_due)
    return t("due.long_term") if g.long_term else t("due.unset")


def _own(g: Goal, person: str) -> bool:
    """这件事是他的：负责人是他，或某个环节由他做。"""
    return g.owner == person or any(s.executor == person for s in g.spans)


def _doing(g: Goal, b: Board) -> str:
    """这个目标现在在干什么的人话；空字符串 = 事都拆给下层在做、本身没动作（「现在在做什么」里不列）。"""
    opened = g.open_spans
    if g.current_pause:
        return pause_kinds()[g.current_pause.kind]
    if opened:
        return t("sep").join(sp.stage for sp in opened)
    if any(b.goals[c].status in ("approved", "active") for c in g.children):
        return ""
    return t("tl.no_stages") if not g.spans else t("doing.stages_done")


def _queue_item(g: Goal, b: Board, now: datetime, viewer: str = "") -> dict:
    helping = [sp for sp in g.open_spans if sp.executor == viewer and g.owner != viewer] if viewer else []
    return {"id": g.id, "gid": g.gnum, "title": g.title, "stage": _doing(g, b),
            "owner": people().get(g.owner, ""), "owner_key": g.owner,
            "due": due_text(g), "late": delay_text(g, now), "due_sort": _due_sort(g),
            "role": t("doing.helping", owner=people().get(g.owner, ""),
                      stages=t("sep").join(sp.stage for sp in helping)) if helping else ""}


def _due_sort(g: Goal) -> tuple[int, str]:
    """「现在在做什么」里的顺序：有计划日的按日子，没定的、长期的排在后面（不靠文字比大小，换了语言也一样）。"""
    return (0, str(g.latest_due)) if g.latest_due else (1, "")


def _in_progress(b: Board, sample: bool) -> list[Goal]:
    """正在推进的目标：进行中、不是示例（示例不是谁手上真有的事）、本身有动作（纯粹拆给下层在做的上层不列，
    免得「现在在做什么」被一串上层占满——要一眼看出各线正在执行的任务）。"""
    return [g for g in b.goals.values()
            if g.status in ("approved", "active") and not g.sample and _doing(g, b)]


def people_queues(b: Board, now: datetime, sample: bool = False, person: str = "") -> list[dict]:
    """每个人手上的事：自己负责的，加上正在替别人做的环节；按计划完成日排。"""
    out = []
    for key, name in people().items():
        if person and key != person:
            continue
        items = [_queue_item(g, b, now, key) for g in _in_progress(b, sample)
                 if g.owner == key or any(sp.executor == key for sp in g.open_spans if g.owner != key)]
        items.sort(key=lambda x: x["due_sort"])   # 「未定」排在日期后面（「长期」也是）
        out.append({"person": name, "key": key, "entries": items})   # 别叫 items：Jinja 会取成 dict.items 方法
    return out


def line_queues(b: Board, now: datetime, sample: bool = False, person: str = "", line: str = "") -> list[dict]:
    """每条线正在做的事（一眼看出各条线正在执行什么）。跨线的块算在它自己显示的那条线。"""
    out = []
    for ln in lines():
        if line and ln != line:
            continue
        items = [_queue_item(g, b, now) for g in _in_progress(b, sample)
                 if g.line == ln and (not person or _own(g, person))]
        items.sort(key=lambda x: x["due_sort"])
        mark, color = config.current().line_marks.get(ln, ("", ""))
        out.append({"line": ln, "mark": mark, "color": color, "entries": items})
    return out


def _order(g: Goal):
    """时间线里同一条线的顶行按编号排：计划日是一开始定的、人记不住，改一次这行就换位置，
    没定日子的全堆在最后；编号顺序最直观。按数字比（G9 在 G10 前），跨线留在自己线上的子块按层级号插进去（G2.3 在 G2 与 G3 之间）。"""
    return tuple(int(x) for x in g.gnum[1:].split("."))


def _matches_person(g: Goal, b: Board, person: str) -> bool:
    """按人筛选时要显示的行：他的事，加上为了带出路径的上层（下面有他的事）。"""
    if not person or _own(g, person):
        return True
    return any(_matches_person(b.goals[c], b, person) for c in g.children)


RANGE_MIN = date(2025, 1, 1)


_BACK_WEEKS = {"week": 0, "2week": 1, "month": 2, "quarter": 11}


def default_left(today: date, zoom: str) -> date:
    """打开时一屏的左边：从周一开始，今天落在靠右的位置（一周档就是本周；一天档就是今天）。"""
    if zoom == "day":
        return today
    return today - timedelta(days=today.weekday(), weeks=_BACK_WEEKS[zoom])


def board_range(today: date, starts: list[date], ends: list[date]) -> tuple[date, date]:
    """整条时间线的起止：盖住所有内容，并且够最大一档（一季度）看满一屏；从周一到周日。"""
    lo = max(min([*starts, default_left(today, "quarter")]), RANGE_MIN)
    hi = max([*ends, today]) + timedelta(days=14)
    return lo - timedelta(days=lo.weekday()), hi + timedelta(days=6 - hi.weekday())


def _nearest_first(items: list[tuple[str, date]], today: date, now_label: str) -> list[tuple[str, date]]:
    """「跳到哪段」的顺序：现在这段在最上面，往下越早；将来的几段放最后。
    这段 = 起始日不晚于今天的最后一项。"""
    cur = max((i for i, (_, d) in enumerate(items) if d <= today), default=None)
    if cur is None:
        return items
    label, d = items[cur]
    return [(t("jump.current", label=label, now=now_label), d)] + items[:cur][::-1] + items[cur + 1:]


def jump_options(start: date, end: date, today: date) -> dict[str, list[tuple[str, date]]]:
    """「跳到哪段」的选项跟着缩放走：一天档按天选，一周、两周档按周选，一个月档按月选，一季度档按季度选。"""
    wd = weekdays()
    weeks = [(t("jump.week", day=f"{d:%m-%d}"), d) for d in (start + timedelta(weeks=i) for i in range((end - start).days // 7 + 1))]
    days_ = [(t("jump.day", day=f"{d:%m-%d}", weekday=wd[d.weekday()]), d) for d in (start + timedelta(days=i) for i in range((end - start).days + 1))]
    months, quarters = [], []
    y, m = start.year, start.month
    while date(y, m, 1) <= end:
        first = max(date(y, m, 1), start)
        months.append((t("jump.month", year=y, month=m, name=t("months").split(",")[m - 1]), first))
        if m in (1, 4, 7, 10) or not quarters:
            quarters.append((t("jump.quarter", year=y, q=(m - 1) // 3 + 1), first))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    weeks = _nearest_first(weeks, today, t("jump.this_week"))
    return {"day": _nearest_first(days_, today, t("jump.today")), "week": weeks, "2week": weeks,
            "month": _nearest_first(months, today, t("jump.this_month")),
            "quarter": _nearest_first(quarters, today, t("jump.this_quarter"))}


def note_rows(b: Board, goal_id: int | None, limit: int = 20) -> list[dict]:
    """口述录入记录；goal_id 给定时只取关于这个目标的。"""
    notes = [n for n in b.notes.values() if goal_id is None or n.goal_id == goal_id]
    return [{"id": n.id, "text": n.text, "who": people().get(n.author, n.author), "who_key": n.author, "at": tz_text(n.at),
             "done": n.resolved_at is not None, "summary": n.summary,
             "done_at": tz_text(n.resolved_at) if n.resolved_at else "",
             "goal_id": n.goal_id,
             "goal_num": b.goals[n.goal_id].gnum if n.goal_id in b.goals else "",
             "goal_title": b.goals[n.goal_id].title if n.goal_id in b.goals else ""}
            for n in sorted(notes, key=lambda n: n.at, reverse=True)[:limit]]


def build_index(conn: sqlite3.Connection, now: datetime, *, line: str, person: str,
                active_only: bool, zoom: str = DEFAULT_ZOOM, sample: bool = False, root: str = "/board") -> dict:
    """首页数据。sample=False 是真实看板，只有真实目标；sample=True 是示例看板（/board/sample）：同一套页面、
    同样的线，真实目标照常显示，再加上假设的示例（标「示例」）——示例要和真实看板一模一样地展示，
    所以示例看板直接读真实数据，不另复制一份。"""
    b, gh = fold(load_events(conn)), GhData(conn)
    problems = []
    if line and line not in lines():
        problems.append(t("idx.no_line", line=line))
        line = ""
    if person and person not in people():
        problems.append(t("idx.no_person", person=person))
        person = ""
    if zoom not in ZOOM_DAYS:
        problems.append(t("idx.no_zoom", zoom=zoom, default=zooms()[DEFAULT_ZOOM][0]))
        zoom = DEFAULT_ZOOM
    today = tz_day(now)
    repo_line = config.current().repo_line

    def visible(g: Goal) -> bool:
        # 不按时间段筛：缩放、拖到哪只改看的范围，内容在哪一档都是全的
        if g.sample and not sample:
            return False
        if active_only and g.status in ("done", "abandoned"):
            return False
        return _matches_person(g, b, person)

    groups = []
    carried = version_carriers(b, sample)
    for ln in lines():
        if line and ln != line:
            continue
        # 这条线的「顶行」：顶层目标，加上从别的线拆过来的跨线子目标（它留在自己的线上显示）
        tops = sorted((g for g in b.goals.values()
                       if g.line == ln and visible(g)
                       and (g.parent_id is None or b.goals[g.parent_id].line != ln
                            or not visible(b.goals[g.parent_id]))), key=_order)   # 上层被藏时自己当顶行
        # 版本行放在挂着它的目标所在的线上（不按仓库归线）。挂的目标分在几条线就在几条线各出现一次；
        # 没有任何目标挂的版本才按仓库归线（配置里每个仓库写了归哪条线）。
        # GitHub 里程碑没有负责人：按人筛选时只带出他目标挂着的版本，不然筛谁都有版本行
        here = {g.version for g in b.goals.values() if g.version and g.line == ln and visible(g)}
        unattached = {r for r in b.versions if r not in carried and repo_line.get(r.split("#")[0]) == ln}
        # 版本只挂一个目标时不单独成行：那样的版本行只是目标行的复读，目标行上现成的小牌子就够了；
        # 挂两个以上目标、或没挂任何目标的版本才成行，行上列出装了哪些目标
        refs = sorted(r for r in here | (unattached if not person else set()) if len(carried.get(r, ())) != 1)
        versions = [(r, [g for g in tops if g.version == r]) for r in refs]
        loose = [g for g in tops if not g.version or g.version not in refs]
        if tops or refs:
            note = ""
        elif person:
            note = t("idx.nothing_for", person=people()[person])
        else:
            note = t("idx.no_goals")
        groups.append(LineGroup(ln, note, versions, loose, sample=sample))
    shown = [g for g in b.goals.values() if visible(g)]
    starts = [tz_day(g.approved_at) for g in shown]
    ends = [d.day for g in shown for d in (g.latest_due, g.baseline_due) if d]
    for ref, vt in b.versions.items():
        m = gh.milestones.get((ref.split("#")[0], int(ref.split("#")[1])))
        starts.append(tz_day(m.created_at if m else vt.tracked_at))
        ends += [d.day for _, d in vt.plans]
    start, end = board_range(today, starts, ends)
    tl = build_timeline(groups, b, gh, visible, now, start, end,
                        match_ok=(lambda g: _own(g, person)) if person else None, root=root)
    blocks = blockers(b, gh, now, sample, root)
    queues = people_queues(b, now, sample, person)
    if person:      # 卡点也跟着筛：只留他的
        blocks = [x for x in blocks if x.goal_id is not None and _own(b.goals[x.goal_id], person)]

    def pct(d: date) -> float:
        return round((d - start).days / tl.days * 100, 3)

    return {
        "fresh": freshness(conn, now), "blockers": blocks,
        "queues": queues, "by_line": line_queues(b, now, sample, person, line),
        "sample": sample, "person": person, "line": line,
        "notes": note_rows(b, None),
        "timeline": tl, "problems": problems, "zoom": zoom, "zooms": zooms(),
        "screens": dict(ZOOM_DAYS),
        "anchors": {z: pct(default_left(today, z)) for z in ZOOM_DAYS},
        "jumps": {z: [(label, pct(d)) for label, d in opts] for z, opts in jump_options(start, end, today).items()},
        "has_samples": any(g.sample for g in b.goals.values()),
        "weekly": sorted(b.weekly.items(), reverse=True)[:8],
    }


def _ts(dt: datetime | None) -> str:
    return iso(dt) if dt else ""


def goal_summary(g: Goal, b: Board, gh: GhData, now: datetime) -> dict:
    """接口里一个目标的样子。带上各个时刻（立项、环节起止、暂停恢复、完成放弃）和挂的版本——
    个人看板拉入时按这些时刻补记，而不是只能按拉取那一刻记。时刻都是带时区的 ISO（UTC），和 occurred_at 一个写法。
    status / owner / paused 是页面上的叫法（跟语言走）；给程序用的另有 status_key / owner_key / paused_kind。"""
    late, ext = delay(g, now)
    return {"id": g.id, "gnum": g.gnum, "permanent": g.permanent, "source": g.source,
            "title": g.title, "line": g.line, "status": status_label(g.status),
            "status_key": "active" if g.status == "approved" else g.status,
            "owner": people().get(g.owner, ""), "owner_key": g.owner, "parent_id": g.parent_id, "sample": g.sample,
            "long_term": g.long_term,
            "baseline_due": str(g.baseline_due or ""),
            "latest_due": str(g.latest_due or ""),
            "current_stages": [sp.stage for sp in g.open_spans],
            "paused": pause_kinds()[g.current_pause.kind] if g.current_pause else "",
            "paused_kind": g.current_pause.kind if g.current_pause else "",
            "stage_days": stage_days(g, now), "pause_days": pause_days(g, now),
            "handoffs": handoffs(g, b),
            "delay_days": late, "delay_external_days": ext, "delay_text": delay_text(g, now),
            "approved_at": _ts(g.approved_at),
            "done_at": _ts(g.done_at), "abandoned_at": _ts(g.abandoned_at),
            "spans": [{"stage": sp.stage, "executor": sp.executor, "start": _ts(sp.start), "end": _ts(sp.end)}
                      for sp in sorted(g.spans, key=lambda x: x.start)],
            "pauses": [{"kind": pause_kinds()[pz.kind], "kind_key": pz.kind, "start": _ts(pz.start), "end": _ts(pz.end),
                        "depends_on": pz.depends_on, "note": pz.note} for pz in g.pauses],
            "due_changes": [{"at": _ts(t), "due": str(d), "reason": r} for t, d, r in g.due_changes],
            "version": ({"ref": g.version, "name": version_name(g.version, gh)} if g.version else None),
            # 目标概要：个人看板拉的时候带过去
            "note": g.note, "done_what": g.done_what, "abandon_reason": g.abandon_reason}


def _wait_text(wait: tuple[timedelta, bool]) -> tuple[str, bool]:
    return duration_text(wait[0]), wait[1]


def build_goal(conn: sqlite3.Connection, b: Board, g: Goal, now: datetime, who: Who, root: str = "/board") -> dict:
    """目标详情只放「一眼看懂」的摘要；改动靠口述交给 AI，手动表单收在备用区。"""
    gh = GhData(conn)
    until = g.closed_at or now
    links = []
    for link in g.links:
        issue = gh.issues.get((link.repo, link.number))
        item = {"kind": link.kind, "ref": f"{link.repo.split('/')[1]}#{link.number}", "synced": issue is not None}
        if issue is not None:
            evs = gh.events.get((link.repo, link.number), [])
            stays = dwell(evs, now)
            item.update({"title": issue.title, "url": issue.url, "state": issue.state,
                         "now": (stays[-1][0], duration_text(now - stays[-1][1])) if stays and stays[-1][2] is None else None,
                         "wait": _wait_text(subcontract_wait(issue, evs, now)) if link.kind == "subcontract" else None})
        links.append(item)
    spent, ext = stage_time(g, now), pause_time(g, now)["external"]
    return {
        "g": g, "status": status_label(g.status), "owner": person_name(g.owner),
        "due_text": due_text(g),
        "parent": b.goals.get(g.parent_id) if g.parent_id else None,
        "children": [{"id": c.id, "gid": c.gnum, "title": c.title, "line": c.line, "owner": person_name(c.owner),
                      "status": status_label(c.status),
                      "now": t("sep").join(sp.stage for sp in c.open_spans) or (t("tl.no_stages") if not c.spans else ""),
                      "due": due_text(c)} for c in (b.goals[i] for i in g.children)],
        "delay": delay(g, now), "delay_text": delay_text(g, now),
        "external": duration_text(ext) if ext else "",       # 延期里等外部的部分（只在延期时显示）
        "since": tz_text(g.approved_at), "total": duration_text(until - g.approved_at),
        # 时长写人话：不满一天写小时、分钟（不然几十分钟的环节都显示成「0.0 天」）
        "stages": [{"stage": st, "spent": duration_text(spent[st]), "running": g.running(st) is not None,
                    "index": stages().index(st)}
                   for st in stages() if any(sp.stage == st for sp in g.spans)],
        "spans": [(s.stage, person_name(s.executor, s.executor), tz_text(s.start), tz_text(s.end) if s.end else t("tl.running"))
                  for s in sorted(g.spans, key=lambda x: x.start)],
        "pause": ({"kind": pause_kinds()[g.current_pause.kind], "since": tz_text(g.current_pause.start),
                   "on": b.goals[g.current_pause.depends_on].title if g.current_pause.depends_on else "",
                   "note": g.current_pause.note} if g.current_pause else None),
        "dues": [(tz_text(at), str(d), r) for at, d, r in g.due_changes],
        "deps": [(b.goals[d.on_goal], d.at_stage, d.need_by) for d in g.deps if d.on_goal in b.goals],
        "blamed": [b.goals[c] for c in blamed_children(g, b, now)],
        "links": links,
        "history": [describe(e, b, who.person, gh) for e in reversed(g.history)],
        # 挂的版本：详情页头部要看到版本名字、能点到版本页
        "version": ({"ref": g.version, "name": version_name(g.version, gh), "href": version_href(g.version, root)}
                    if g.version else None),
        "ended_at": tz_text(g.closed_at) if g.closed_at else "",
        "can_edit": who.person == g.owner or is_team_owner(who.person), "is_team_owner": is_team_owner(who.person),
        "open_stages": [sp.stage for sp in g.open_spans],
        "other_goals": [(x.id, x.title) for x in b.goals.values()       # 示例只能等示例、真实只能等真实
                        if x.id != g.id and x.status not in ("done", "abandoned") and x.sample == g.sample],
        "notes": note_rows(b, g.id),
    }


def build_version(conn: sqlite3.Connection, b: Board, repo: str, number: int, now: datetime) -> dict:
    gh = GhData(conn)
    ref = f"{repo}#{number}"
    m = gh.milestones.get((repo, number))
    vt = b.versions.get(ref)
    moves = [mv for mv in milestone_moves(gh, repo) if m and m.title in (mv.src, mv.dst)]
    history = [describe(e, b, "", gh) for e in reversed(list(b.by_id.values())) if e.subject == f"version:{ref}"]
    return {
        "ref": ref, "repo": repo, "number": number, "m": m, "vt": vt,
        "title": m.title if m else ref,
        "gh_due": gh_due_day(m.due_on) if m and m.due_on else None,
        "late": late_text(vt.baseline.at, version_done_at(vt, m) or now) if vt and vt.baseline else "",
        "goals": [g for g in b.goals.values() if g.version == ref],
        # 这版做了什么：挂在这个版本下已完成的目标，按完成先后；没写「做了什么」的就是标题本身
        "whats_new": sorted((g for g in b.goals.values() if g.version == ref and g.status == "done"), key=lambda g: g.done_at),
        "goal_status": {g.id: status_label(g.status) + (f" {tz_day(g.closed_at):%m-%d}" if g.closed_at else "")
                        for g in b.goals.values() if g.version == ref},
        "done_text": tz_text(version_done_at(vt, m)) if version_done_at(vt, m) else "",
        "spans": [(st, tz_text(ab[0]), tz_text(ab[1]), duration_text(ab[1] - ab[0]))
                  for st, ab in stage_spans([g for g in b.goals.values() if g.version == ref], now).items()
                  if ab],
        "moved_in": [{"number": mv.number, "title": mv.title, "src": mv.src, "dst": mv.dst,
                      "at": tz_text(mv.at)} for mv in moves if m and mv.dst == m.title],
        "moved_out": [{"number": mv.number, "title": mv.title, "src": mv.src, "dst": mv.dst,
                       "at": tz_text(mv.at)} for mv in moves if m and mv.src == m.title],
        "history": history,
    }
