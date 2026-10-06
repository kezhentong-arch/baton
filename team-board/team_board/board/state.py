"""把事件折叠成当前状态，并算出看板要的数字。全是纯函数，`now` 由调用方传入。

口径：耗时是日历时间；暂停期间不算进任何环节；延期以立项时的基准日为准，
「等外部」的天数单独写出。环节可以重叠、反复交替，不算「回退」。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from team_board import config
from team_board.board.model import PAUSE_KEYS, STALE_STAGE_DAYS, Due, days, late_text, parse_day, stages
from team_board.board.store import Event
from team_board.i18n import t


@dataclass
class StageSpan:
    stage: str
    executor: str
    start: datetime
    end: datetime | None = None


@dataclass
class Pause:
    kind: str
    start: datetime
    end: datetime | None = None
    depends_on: int | None = None
    note: str = ""


@dataclass
class Dependency:
    on_goal: int
    at_stage: str
    need_by: Due | None


@dataclass
class Link:
    repo: str
    number: int
    kind: str  # link | subcontract


@dataclass
class Goal:
    id: int
    title: str
    line: str
    parent_id: int | None
    version: str | None
    note: str
    proposed_by: str
    proposed_at: datetime
    status: str = "approved"          # 看板从立项开始，建目标就是立项
    sample: bool = False              # 演示用的假设数据（示例看板上的案例），不是真实进度
    long_term: bool = False           # 长期负责的事：没有完成日，显示「长期」而不是「计划未定」
    approved_at: datetime | None = None
    baseline_due: Due | None = None
    due_changes: list[tuple[datetime, Due, str]] = field(default_factory=list)
    owner: str = ""
    spans: list[StageSpan] = field(default_factory=list)
    pauses: list[Pause] = field(default_factory=list)
    deps: list[Dependency] = field(default_factory=list)
    links: list[Link] = field(default_factory=list)
    done_at: datetime | None = None
    abandoned_at: datetime | None = None
    children: list[int] = field(default_factory=list)
    history: list[Event] = field(default_factory=list)
    voided_ids: set[int] = field(default_factory=set)   # history 里被作废的那些
    seq: int = 0                      # 在上层目标下是第几块（拆出来那一刻定下，不变、不回收；顶层为 0）
    gnum: str = ""                    # 看板上的编号：顶层 G17，拆出来的块 G17.1、G17.1.2（编号要看得出从属）
    source: str = ""                  # 来源号：个人看板立项时发的出生号（例 A16），推上来时记下，一辈子不变；团队看板直接立的没有
    # 目标概要：「做什么」就是立项说明 note；「做了什么」完成时写（What's new 写法），版本页汇总；
    # 放弃的原因放在同一栏。只在立项、完成两个时刻写，之后不维护
    done_what: str = ""
    abandon_reason: str = ""

    @property
    def permanent(self) -> str:
        """永久号：不带点的 G 号 = 内部编号，改挂不变（带点的层级号只是显示）。提交信息里写它或来源号。"""
        return f"G{self.id}"

    @property
    def latest_due(self) -> Due | None:
        return self.due_changes[-1][1] if self.due_changes else self.baseline_due

    @property
    def open_spans(self) -> list[StageSpan]:
        """正在进行的环节（几个环节可以同时进行）。"""
        return [s for s in self.spans if s.end is None]

    @property
    def current_span(self) -> StageSpan | None:
        """最近开始的、还在进行的那一段（兼容只看一段的地方）。"""
        opened = self.open_spans
        return max(opened, key=lambda s: s.start) if opened else None

    def running(self, stage: str) -> StageSpan | None:
        return next((s for s in self.spans if s.stage == stage and s.end is None), None)

    @property
    def last_stage_change(self) -> datetime | None:
        ts = [t for s in self.spans for t in (s.start, s.end) if t is not None]
        return max(ts) if ts else None

    @property
    def current_pause(self) -> Pause | None:
        return self.pauses[-1] if self.pauses and self.pauses[-1].end is None else None

    @property
    def closed_at(self) -> datetime | None:
        return self.done_at or self.abandoned_at


@dataclass
class VersionTrack:
    ref: str
    tracked_at: datetime
    plans: list[tuple[datetime, Due]] = field(default_factory=list)
    done_at: datetime | None = None

    @property
    def baseline(self) -> Due | None:
        return self.plans[0][1] if self.plans else None

    @property
    def latest(self) -> Due | None:
        return self.plans[-1][1] if self.plans else None

    @property
    def last_at(self) -> datetime:
        """这个版本最后一条记录的发生时间（补录不能早于它）。"""
        return max([self.tracked_at, *(t for t, _ in self.plans), *([self.done_at] if self.done_at else [])])


@dataclass
class Note:
    """口述录入：人写下的原始进展，复制给 AI 录入；AI 录完标「已录入」。"""
    id: int
    text: str
    author: str
    at: datetime
    goal_id: int | None = None
    resolved_at: datetime | None = None
    resolved_by: str = ""
    summary: str = ""


@dataclass
class Board:
    goals: dict[int, Goal] = field(default_factory=dict)
    versions: dict[str, VersionTrack] = field(default_factory=dict)
    weekly: dict[date, str] = field(default_factory=dict)
    notes: dict[int, Note] = field(default_factory=dict)
    # 被作废的记录：事件 id → 作废它的那条事件（只追加，作废也是追加一条）
    voided: dict[int, Event] = field(default_factory=dict)
    by_id: dict[int, Event] = field(default_factory=dict)


def fold(events: list[Event]) -> Board:
    """事件 → 状态。遇到前后矛盾的记录直接抛错：写入口会在提交前重算一次，
    抛错就整条撤销，所以矛盾的记录（例如作废了一个后面还被用到的环节开始）进不了库。"""
    b = Board()
    b.by_id = {e.id: e for e in events}
    for e in events:
        if e.kind == "event.voided":
            b.voided[e.payload["event_id"]] = e
    # 每块在上层下的序号：写入口会把 seq 存进记录；没有 seq 的记录按出现先后补——撤掉的目标也占号，
    # 这样后来的号不会因为前面撤了一个而变
    seqs: dict[int, int] = {}
    counters: dict[int | None, int] = {}
    for e in events:
        if e.kind == "goal.proposed" or (e.kind == "goal.edited" and "parent_id" in e.payload):
            gid = int(e.subject[5:])
            parent = e.payload.get("parent_id")
            if parent is None:
                seqs[gid] = 0
                continue
            counters[parent] = counters.get(parent, 0) + 1
            if e.id in b.voided:          # 作废的挪动：号占着（不回收），但目标的 seq 回到作废前那条
                continue
            seqs[gid] = int(e.payload.get("seq") or counters[parent])
    # 建目标那条被作废 = 整个目标撤掉（只在它还没有后续记录时允许，见 actions._void）
    withdrawn = {b.by_id[i].subject for i in b.voided
                 if i in b.by_id and b.by_id[i].kind == "goal.proposed"}
    for e in events:
        if e.subject in withdrawn:
            continue
        if e.kind == "event.voided":
            target = b.by_id.get(e.payload["event_id"])
            if target is None or target.kind == "event.voided":
                raise ValueError(t("fold.void_target", id=e.payload["event_id"]))
            if e.subject.startswith("goal:") and int(e.subject[5:]) in b.goals:
                b.goals[int(e.subject[5:])].history.append(e)
            continue
        if e.id in b.voided:
            if e.subject.startswith("goal:") and int(e.subject[5:]) in b.goals:
                b.goals[int(e.subject[5:])].voided_ids.add(e.id)  # 完成 / 放弃的时间下限跳过它（actions._after_all_records）；那一刻的看板也不算它（actions._as_of）
                b.goals[int(e.subject[5:])].history.append(e)     # 留痕里照样显示，标「已作废」
            continue
        if e.subject.startswith("goal:"):
            _apply_goal(b, int(e.subject[5:]), e)
        elif e.subject.startswith("version:"):
            _apply_version(b, e.subject[8:], e)
        elif e.subject == "board" and e.kind == "weekly.linked":
            b.weekly[parse_day(e.payload["week_start"])] = e.payload["url"]
        elif e.subject == "inbox":
            _apply_note(b, e)
    for g in b.goals.values():
        g.seq = seqs.get(g.id, 0)
    sources: dict[str, int] = {}
    for g in b.goals.values():   # 来源号全库唯一：写入口查过一遍，这里再兜一次（作废一条补来源号的记录也可能撞号）
        if g.source:
            if g.source in sources:
                raise ValueError(t("fold.source_dup", source=g.source, a=f"G{sources[g.source]}", b=f"G{g.id}"))
            sources[g.source] = g.id
    for g in b.goals.values():
        g.gnum = _gnum(b, g)
        # 同一上层下的块按编号排。children 原本按立项时间先后进来：先在个人看板立、收尾才推上来的目标
        # 立项时间早、号却发得晚，就会排到号更小的块上面。号发出去不变，所以不重新编号，改排序；
        # 时间线和详情页的子目标表都读这个顺序
        g.children.sort(key=lambda c: b.goals[c].seq)
    return b


def _gnum(b: Board, g: Goal) -> str:
    if g.parent_id is None:
        return f"G{g.id}"
    return f"{_gnum(b, b.goals[g.parent_id])}.{g.seq}"


def resolve(b: Board, num: str) -> Goal | None:
    """任意一种号 → 同一个目标（提交信息里写的号永远查得到）。
    来源号（个人看板发的出生号：本人字母＋序号，例 A16）；不带点的 G27 = 内部编号（顶层目标的显示号也就是它）；
    带点的 G2.5 = 此刻的层级显示号（改挂后会变，只按现在的层级认）。对不上返回 None。"""
    key = num.strip().upper()
    if re.fullmatch(config.current().source_re, key):
        return next((g for g in b.goals.values() if g.source == key), None)
    if re.fullmatch(r"G[1-9][0-9]*", key):
        return b.goals.get(int(key[1:]))
    if re.fullmatch(r"G[1-9][0-9]*(\.[1-9][0-9]*)+", key):
        return next((g for g in b.goals.values() if g.gnum == key), None)
    return None


def _apply_note(b: Board, e: Event) -> None:
    if e.kind == "note.added":
        b.notes[e.id] = Note(e.id, e.payload["text"], e.actor, e.occurred_at, e.payload.get("goal_id"))
    elif e.kind == "note.resolved":
        n = b.notes[e.payload["note_id"]]
        n.resolved_at, n.resolved_by, n.summary = e.occurred_at, e.actor, e.payload.get("summary", "")


def _close_open(g: Goal, t: datetime) -> None:
    for s in g.open_spans:
        s.end = t
    if g.current_pause:
        g.current_pause.end = t


def _apply_goal(b: Board, gid: int, e: Event) -> None:
    p, at = e.payload, e.occurred_at
    if e.kind == "goal.proposed":
        g = Goal(id=gid, title=p["title"], line=p["line"], parent_id=p.get("parent_id"),
                 version=p.get("version"), note=p.get("note", ""),
                 proposed_by=e.actor, proposed_at=at, approved_at=at, sample=bool(p.get("sample")),
                 long_term=bool(p.get("long_term")), source=p.get("source") or "")
        b.goals[gid] = g
        if g.parent_id is not None:
            b.goals[g.parent_id].children.append(gid)
        g.history.append(e)
        return
    g = b.goals[gid]
    g.history.append(e)
    k = e.kind
    if k == "goal.approved":
        bd = p.get("baseline_due")
        g.approved_at, g.baseline_due = at, Due.parse(bd) if bd else None
    elif k == "goal.edited":
        for key in ("title", "note", "done_what"):
            if key in p:
                setattr(g, key, p[key])
        if "line" in p:
            _set_line(b, g, p["line"])
        if "version" in p:
            g.version = p["version"] or None
        if "long_term" in p:
            g.long_term = bool(p["long_term"])
        if "source" in p:
            g.source = p["source"] or ""
        if "parent_id" in p:
            if g.parent_id is not None:
                b.goals[g.parent_id].children.remove(gid)
            g.parent_id = p["parent_id"]
            if g.parent_id is not None:
                b.goals[g.parent_id].children.append(gid)   # 挂到哪个上层下面不改它自己的线（可以跨线）
    elif k == "goal.assigned":
        g.owner = p["owner"]
    elif k == "stage.started":           # 并行开始一个环节
        if g.running(p["stage"]):
            raise ValueError(t("err.stage_running", stage=p["stage"], at=""))
        g.spans.append(StageSpan(p["stage"], p["executor"], at))
        if g.status == "approved":
            g.status = "active"
    elif k == "stage.ended":
        span = g.running(p["stage"])
        if span is None:
            raise ValueError(t("fold.stage_not_running", stage=p["stage"]))
        span.end = at
    elif k == "pause.started":
        g.pauses.append(Pause(p["kind"], at, None, p.get("depends_on"), p.get("note", "")))
    elif k == "pause.ended":
        if g.current_pause is None:
            raise ValueError(t("fold.not_paused"))
        g.current_pause.end = at
    elif k == "due.changed":
        if g.baseline_due is None:       # 立项时没定日期：第一次定的就是基准
            g.baseline_due = Due.parse(p["due"])
        else:
            g.due_changes.append((at, Due.parse(p["due"]), p["reason"]))
    elif k == "dep.declared":
        nb = p.get("need_by")
        g.deps.append(Dependency(p["on_goal"], p["at_stage"], Due.parse(nb) if nb else None))
    elif k == "dep.removed":
        if not any(d.on_goal == p["on_goal"] for d in g.deps):
            raise ValueError(t("err.no_such_dep"))
        g.deps = [d for d in g.deps if d.on_goal != p["on_goal"]]
    elif k == "issue.linked":
        g.links.append(Link(p["repo"], p["number"], p["kind"]))
    elif k == "issue.unlinked":
        g.links = [x for x in g.links if (x.repo, x.number) != (p["repo"], p["number"])]
    elif k == "goal.completed":
        _close_open(g, at)
        g.status, g.done_at = "done", at
        if "done_what" in p:            # 完成时没写就不动（作废完成再完成时，之前改的不被清掉）
            g.done_what = p["done_what"]
    elif k == "goal.abandoned":
        _close_open(g, at)
        g.status, g.abandoned_at = "abandoned", at
        g.abandon_reason = p.get("reason", "")


def _set_line(b: Board, g: Goal, line: str) -> None:
    """换线：原来和它同一条线的下层跟着走；本来就在别的线上的下层（跨线子目标）留在原地。
    一个业务目标可以拆到不同的线（例：一个产品功能既有产品线的块，也有运营线上的后台配置）。"""
    old = g.line
    g.line = line
    for c in g.children:
        if b.goals[c].line == old:
            _set_line(b, b.goals[c], line)


def _apply_version(b: Board, ref: str, e: Event) -> None:
    if e.kind == "version.tracked":
        b.versions[ref] = VersionTrack(ref, e.occurred_at)
    elif e.kind == "version.planned":
        b.versions[ref].plans.append((e.occurred_at, Due.parse(e.payload["due"])))
    elif e.kind == "version.completed":
        b.versions[ref].done_at = e.occurred_at


def _until(g: Goal, now: datetime) -> datetime:
    return g.closed_at or now


def _overlap(a0: datetime, a1: datetime, b0: datetime, b1: datetime) -> timedelta:
    lo, hi = max(a0, b0), min(a1, b1)
    return hi - lo if hi > lo else timedelta(0)


def stage_time(g: Goal, now: datetime) -> dict[str, timedelta]:
    """各环节耗时（日历时间），扣掉暂停。页面按它写人话时长（不满一天写小时、分钟），接口按它折成天数。"""
    until = _until(g, now)
    raw = dict.fromkeys(stages(), timedelta(0))
    for s in g.spans:
        s_end = s.end or until
        spent = s_end - s.start
        for p in g.pauses:
            spent -= _overlap(s.start, s_end, p.start, p.end or until)
        raw[s.stage] += spent
    return raw


def stage_days(g: Goal, now: datetime) -> dict[str, float]:
    """各环节耗时（天，一位小数）：接口里的 stage_days。"""
    return {k: days(v) for k, v in stage_time(g, now).items()}


def pause_time(g: Goal, now: datetime) -> dict[str, timedelta]:
    """各种暂停一共停了多久。页面写人话时长，接口折成天数（pause_days）。"""
    until = _until(g, now)
    raw = dict.fromkeys(PAUSE_KEYS, timedelta(0))
    for p in g.pauses:
        raw[p.kind] += (p.end or until) - p.start
    return raw


def pause_days(g: Goal, now: datetime) -> dict[str, float]:
    return {k: days(v) for k, v in pause_time(g, now).items()}


def handoffs(g: Goal, b: Board) -> int:
    """跨人交接次数：由负责人以外的人做的每一段算一次；子目标的负责人和上层不是同一人，
    再算一次（业务交给负责人）。几个环节可以同时进行，所以不再按「相邻两段」算。"""
    n = sum(1 for s in g.spans if g.owner and s.executor != g.owner)
    if g.parent_id is not None and g.owner and g.owner != b.goals[g.parent_id].owner:
        n += 1
    return n


def late_days(deadline: datetime, end: datetime) -> float:
    """实际超出几天（保留两位小数，3 小时 = 0.13），和页面的 late_text 同一口径：不满 1 小时算 0、不向上取整
    （向上取整成整天的话，过了 1 分钟就算 1 天）。"""
    sec = (end - deadline).total_seconds()
    return round(sec / 86400, 2) if sec >= 3600 else 0.0


def delay(g: Goal, now: datetime) -> tuple[float, float]:
    """(超出基准日的天数, 其中等外部的天数)。没有基准日或已放弃的不算延期。接口里的 delay_days 用它。"""
    if g.baseline_due is None or g.status == "abandoned":
        return 0, 0.0
    late = late_days(g.baseline_due.at, _until(g, now))
    return (late, pause_days(g, now)["external"]) if late else (0, 0.0)


def delay_text(g: Goal, now: datetime) -> str:
    """页面上写的延期：不满一天按小时（计划到小时后，延 3 小时不该写成「延期 1 天」）。"""
    if g.baseline_due is None or g.status == "abandoned":
        return ""
    return late_text(g.baseline_due.at, _until(g, now))


def blamed_children(g: Goal, b: Board, now: datetime) -> list[int]:
    """拖过了上层预计完成日的子目标。"""
    if g.latest_due is None:
        return []
    deadline = g.latest_due.at
    out = []
    for cid in g.children:
        c = b.goals[cid]
        if c.status == "abandoned":
            continue
        if c.done_at:
            end = c.done_at
        elif c.latest_due:
            end = max(now, c.latest_due.at)
        else:
            end = now
        if end > deadline:
            out.append(cid)
    return out


def dependency_warnings(b: Board, now: datetime) -> list[tuple[int, int, str]]:
    """(依赖方, 被依赖方, 说明)：被依赖目标预计完成日晚于需要它的日子。"""
    out = []
    for g in b.goals.values():
        if g.status in ("done", "abandoned"):
            continue
        for d in g.deps:
            dep = b.goals.get(d.on_goal)
            if dep is None or dep.status == "done":
                continue
            need = d.need_by or g.latest_due
            if dep.latest_due is None:
                out.append((g.id, dep.id, t("dep.no_due", title=dep.title)))
            elif need is not None and dep.latest_due > need:
                out.append((g.id, dep.id, t("dep.late", title=dep.title, due=dep.latest_due, need=need)))
    return out


def is_stale(g: Goal, last_activity: datetime | None, now: datetime) -> bool:
    """环节记录超过 STALE_STAGE_DAYS 天没动过，但关联的单最近 STALE_STAGE_DAYS 天里有动静。"""
    if g.status != "active" or g.current_pause or not g.open_spans:
        return False
    window = timedelta(days=STALE_STAGE_DAYS)
    if g.last_stage_change is None or now - g.last_stage_change < window:
        return False
    return last_activity is not None and now - last_activity < window


def stage_spans(goals: list[Goal], now: datetime) -> dict[str, tuple[datetime, datetime] | None]:
    """版本这一层按跨度看：各目标里第一个进入某环节，到最后一个离开它的时间。"""
    out: dict[str, tuple[datetime, datetime] | None] = dict.fromkeys(stages())
    for g in goals:
        until = _until(g, now)
        for s in g.spans:
            a, c = s.start, s.end or until
            cur = out[s.stage]
            out[s.stage] = (min(cur[0], a), max(cur[1], c)) if cur else (a, c)
    return out
