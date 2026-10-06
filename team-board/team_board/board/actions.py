"""看板上所有写操作的唯一入口：网页表单、JSON 接口、终端 / AI 都走这里。

先校验（身份、权限、参数、状态、时间），全部通过才写；任何一步失败，一条都不写。

谁能做什么只认配置里的角色（owner / member）和目标的负责人，不认具体的人：
- owner 角色：新开目标、拆给别人、换负责人、放弃、改挂 / 换线、定版本计划、补来源号；别人目标上的事也都能记。
- 每个人：只能录自己负责的目标；可以在自己负责的目标下面拆子目标给自己；
  替别人做环节的人可以记自己那一段的起止。
"""
from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from team_board import config
from team_board.board.model import (FUTURE_TOLERANCE, PAUSE_KEYS, Due, gh_due_day, is_team_owner, lines, parse_day,
                                    parse_ts, people, person_name, repos, stages, status_label, tz_note, tz_text)
from team_board.board.state import Board, Goal, fold
from team_board.board.store import append_event, load_events, new_goal_id
from team_board.i18n import t


class ActionError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass(frozen=True)
class Who:
    person: str
    via: str  # web | ai | seed

    @property
    def label(self) -> str:
        return people()[self.person] + (t("via.ai") if self.via == "ai" else "")


@dataclass(frozen=True)
class Result:
    event_ids: list[int] = field(default_factory=list)
    goal_id: int | None = None


# 每个操作收哪些字段。说明文字（做什么、谁能做）在翻译表里，见 action_specs()。
# 所有操作另外都接受 occurred_at（带时区的时间，用于补录）。
_FIELDS: dict[str, tuple[list[str], list[str]]] = {
    "create": (["title", "owner"], ["line", "parent_id", "due", "note", "version", "long_term", "sample", "source"]),
    "assign": (["goal_id", "owner"], []),
    "start_stage": (["goal_id", "stage"], ["executor"]),
    "end_stage": (["goal_id", "stage"], []),
    "pause": (["goal_id", "kind"], ["depends_on", "note"]),
    "resume": (["goal_id"], []),
    "change_due": (["goal_id", "due", "reason"], []),
    "declare_dependency": (["goal_id", "on_goal", "at_stage"], ["need_by"]),
    "remove_dependency": (["goal_id", "on_goal"], []),
    "link_issue": (["goal_id", "repo", "number", "kind"], []),
    "unlink_issue": (["goal_id", "repo", "number"], []),
    "edit_goal": (["goal_id"], ["title", "note", "line", "version", "parent_id", "long_term", "source", "done_what"]),
    "complete": (["goal_id"], ["done_what"]),
    "abandon": (["goal_id", "reason"], []),
    "track_version": (["ref"], []),
    "plan_version": (["ref", "due"], []),
    "complete_version": (["ref"], []),
    "link_weekly": (["week_start", "url"], []),
    "add_note": (["text"], ["goal_id"]),
    "resolve_note": (["note_id", "summary"], []),
    "void": (["event_id", "reason"], []),
}
# 这些操作要先在配置里开启 GitHub 同步（版本就是 GitHub 里程碑）
GITHUB_ACTIONS = frozenset({"link_issue", "unlink_issue", "track_version", "plan_version", "complete_version"})


def action_specs() -> dict[str, dict]:
    """每个操作的说明：页面、命令行、MCP 都读这一份（GET /api/board/actions）。没开 GitHub 同步时不列那几个操作。"""
    enabled = bool(repos())
    return {name: {"desc": t(f"act.{name}.desc"), "who": t(f"act.{name}.who"),
                   "required": list(req), "optional": list(opt)}
            for name, (req, opt) in _FIELDS.items() if enabled or name not in GITHUB_ACTIONS}


def _keys(action: str) -> set[str]:
    req, opt = _FIELDS[action]
    return set(req) | set(opt)


_VERSION_RE = re.compile(r"^(?P<repo>[\w.-]+/[\w.-]+)#(?P<number>[1-9]\d*)$")
_ENDED = ("done", "abandoned")


def _sep() -> str:
    return t("sep")


class _P:
    """参数读取器：缺、错、多都在写入前报错（输入严格）。"""

    def __init__(self, params: dict, allowed: set[str]):
        extra = set(params) - allowed - {"occurred_at"}
        if extra:
            raise ActionError(400, t("err.unknown_params", names=_sep().join(sorted(extra))))
        self.p = params

    def text(self, key: str, *, required: bool = True, max_len: int = 200) -> str:
        v = self.p.get(key)
        if v is None or (isinstance(v, str) and not v.strip()):
            if required:
                raise ActionError(400, t("err.missing", key=key))
            return ""
        if not isinstance(v, str):
            raise ActionError(400, t("err.must_be_text", key=key))
        v = v.strip()
        if len(v) > max_len:
            raise ActionError(400, t("err.too_long", key=key, n=max_len))
        return v

    def choice(self, key: str, options, *, required: bool = True) -> str:
        v = self.text(key, required=required)
        if v and v not in options:
            raise ActionError(400, t("err.one_of", key=key, options=_sep().join(options)))
        return v

    def day(self, key: str, *, required: bool = True) -> str:
        v = self.text(key, required=required)
        if v:
            try:
                parse_day(v)
            except ValueError:
                raise ActionError(400, t("err.not_a_date", key=key)) from None
        return v

    def due(self, key: str, *, required: bool = True) -> str:
        """计划完成：到天或到小时，返回规整后的写法（2026-10-15 / 2026-10-15 08:00）。"""
        v = self.text(key, required=required)
        if not v:
            return ""
        try:
            return str(Due.parse(v))
        except ValueError:
            raise ActionError(400, t("err.due_format", key=key, tz=tz_note())) from None

    def integer(self, key: str, *, required: bool = True) -> int | None:
        v = self.p.get(key)
        if v is None or v == "":
            if required:
                raise ActionError(400, t("err.missing", key=key))
            return None
        if isinstance(v, bool):
            raise ActionError(400, t("err.must_be_int", key=key))
        try:
            n = int(v)
        except (TypeError, ValueError):
            raise ActionError(400, t("err.must_be_int", key=key)) from None
        if n <= 0:
            raise ActionError(400, t("err.must_be_positive", key=key))
        return n

    def flag(self, key: str) -> bool:
        v = self.p.get(key, False)
        if v in (True, "1", "true", "on"):
            return True
        if v in (False, "0", "false", "", None):
            return False
        raise ActionError(400, t("err.must_be_flag", key=key))


Handler = Callable[[sqlite3.Connection, Board, dict, Who, datetime, datetime], Result]


def _emit(conn, subject: str, kind: str, payload: dict, who: Who, now: datetime, occ: datetime) -> int:
    return append_event(conn, subject=subject, kind=kind, payload=payload, actor=who.person,
                        via=who.via, now=now, occurred_at=occ)


def _goal(b: Board, gid: int | None) -> Goal:
    g = b.goals.get(gid) if gid is not None else None
    if g is None:
        raise ActionError(404, t("err.no_goal", id=gid))
    return g


def _need_team_owner(who: Who) -> None:
    if not is_team_owner(who.person):
        raise ActionError(403, t("err.team_owner_only"))


def _need_owner(g: Goal, who: Who) -> None:
    if who.person != g.owner and not is_team_owner(who.person):
        raise ActionError(403, t("err.goal_owner_only", owner=person_name(g.owner)))


def _need_status(g: Goal, *ok: str, at: datetime | None = None) -> None:
    """at 给的是补录时刻：报错要说「那时」是什么状态，不是「现在」。"""
    if g.status not in ok:
        when = t("when.then", time=tz_text(at), tz=tz_note()) if at is not None else t("when.now")
        raise ActionError(409, t("err.bad_status", when=when, status=status_label(g.status)))


def _as_of(b: Board, occ: datetime) -> Board:
    """那一刻的看板：只算发生时间不晚于 occ 的记录。

    补录允许插到任何位置，校验的是「和那一刻的状态一致」：个人看板往团队看板推本来就是补录
    （时刻取个人看板记的那一刻），而团队看板上常常已经有更晚的记录——改说明、挂版本、别人记的段——
    「只能补在最后一条记录之后」会把正常推送挡住。
    插进去之后和后面记录矛盾的（同一环节重复开始、结束了两次）由 apply_action 提交前的整体重算拦下。
    作废是事后更正，不看发生时间：被作废的记录在任何时刻都不算数。"""
    events = list(b.by_id.values())            # load_events 已按发生时间排好
    if all(e.occurred_at <= occ for e in events if e.kind != "event.voided"):
        return b                               # 不是补录、或补在所有记录之后：那一刻就是现在
    keep = [e for e in events if e.kind != "event.voided" and e.occurred_at <= occ]
    ids = {e.id for e in keep}
    voids = [e for e in events if e.kind == "event.voided" and e.payload["event_id"] in ids]
    return fold(sorted(keep + voids, key=lambda e: (e.occurred_at, e.id)))


def _goal_then(b: Board, gid: int | None, occ: datetime) -> tuple[Goal, Goal]:
    """返回（那一刻的目标，现在的目标）。状态类校验看前者，权限、结构（上层、序号）看后者。
    补录早于立项直接拒绝：时间线上不能有立项前的记录。"""
    now_g = _goal(b, gid)
    then_g = _as_of(b, occ).goals.get(now_g.id)
    if then_g is None:
        raise ActionError(409, t("err.before_created", gnum=now_g.gnum, title=now_g.title,
                                 time=tz_text(now_g.approved_at), tz=tz_note()))
    return then_g, now_g


def _then(then_g: Goal, now_g: Goal, occ: datetime) -> datetime | None:
    """补录时才带时刻（报错说「那时」）；现在记的就不带。"""
    return occ if then_g is not now_g else None


def _at(then_g: Goal, now_g: Goal, occ: datetime) -> str:
    return t("when.then", time=tz_text(occ), tz=tz_note()) if then_g is not now_g else ""


def _after_all_records(g: Goal, occ: datetime) -> None:
    """完成 / 放弃之后不会再有记录，所以它们只能记在这个目标最后一条有效记录之后（其余操作没有这个限制，
    见 _as_of）。作废记录和被作废的记录不算。"""
    live = [e for e in g.history if e.kind != "event.voided" and e.id not in g.voided_ids]
    if live and occ < live[-1].occurred_at:
        raise ActionError(409, t("err.close_after_last", time=tz_text(live[-1].occurred_at), tz=tz_note()))


def _after_version(vt, occ: datetime) -> None:
    """版本完成之后不会再有记录，所以只能记在这个版本最后一条记录之后（计划日期可以插到任何位置，见 _plan_version）。"""
    if occ < vt.last_at:
        raise ActionError(409, t("err.version_close_after_last", time=tz_text(vt.last_at), tz=tz_note()))


def _version_ref(ref: str) -> tuple[str, int]:
    if not repos():
        raise ActionError(400, t("err.github_off"))
    m = _VERSION_RE.match(ref)
    if not m or m["repo"] not in repos():
        raise ActionError(400, t("err.version_ref", repos=_sep().join(repos())))
    return m["repo"], int(m["number"])


def _letters_help() -> str:
    cfg = config.current()
    return " / ".join(f"{p.letter} {p.name}" for p in cfg.persons)


def _source(b: Board, raw: object) -> str:
    """来源号：格式（本人字母＋序号）与全看板唯一。撤掉的目标不占号——个人看板发号本来就不重用。"""
    v = str(raw or "").strip().upper()
    if not re.fullmatch(config.current().source_re, v):
        raise ActionError(400, t("err.source_format", letters=_letters_help(), value=repr(raw),
                                 example=f"{config.current().persons[0].letter}16"))
    taken = next((g for g in b.goals.values() if g.source == v), None)
    if taken is not None:
        raise ActionError(409, t("err.source_taken", source=v, gnum=taken.gnum, title=taken.title))
    return v


DONE_WHAT_MAX = 1000   # 「做了什么」条数不限，给到 1000 字；配套的个人看板同一上限，推上来不会被拒


def _create(conn, b, params, who, now, occ) -> Result:
    p = _P(params, _keys("create"))
    title, owner = p.text("title", max_len=80), p.choice("owner", people())
    source = _source(b, params["source"]) if str(params.get("source") or "").strip() else ""
    my_letter = config.current().letters[who.person]
    if source and source[0] != my_letter:
        # 出生号是谁的个人看板发的，就由谁推上来（个人看板以本人身份推）；字母对不上多半是填错了人或号
        raise ActionError(400, t("err.source_letter", source=source, letter_owner=_letter_owner(source),
                                 me=people()[who.person], letter=my_letter))
    line = p.choice("line", lines(), required=False)
    due, note = p.due("due", required=False), p.text("note", required=False, max_len=500)
    version = p.text("version", required=False)
    if version:
        _version_ref(version)
    pid = p.integer("parent_id", required=False)
    parent_then, parent = _goal_then(b, pid, occ) if pid is not None else (None, None)
    _may_create(who, parent, owner)
    sample, long_term = p.flag("sample"), p.flag("long_term")
    if long_term and due:
        raise ActionError(400, t("err.long_term_with_due"))
    if parent is not None and sample and not parent.sample:
        raise ActionError(400, t("err.sample_under_sample"))
    if parent is None and not line:
        raise ActionError(400, t("err.line_missing"))
    if parent is not None:
        _need_status(parent_then, "approved", "active", at=_then(parent_then, parent, occ))
        _not_before_parent(parent, occ)
        line = line or parent.line       # 不填就跟上层同线；填了别的线就是跨线的子目标
    gid = new_goal_id(conn, now)
    s = f"goal:{gid}"
    ids = [
        _emit(conn, s, "goal.proposed", {"title": title, "line": line,
                                         "parent_id": parent.id if parent else None,
                                         "seq": _next_seq(b, parent.id) if parent else 0,
                                         "version": version or (parent.version if parent else None),
                                         "note": note, "sample": parent.sample if parent else sample,
                                         **({"long_term": True} if long_term else {}),
                                         **({"source": source} if source else {})},
              who, now, occ),
        _emit(conn, s, "goal.approved", {"baseline_due": due or None}, who, now, occ),
        _emit(conn, s, "goal.assigned", {"owner": owner}, who, now, occ),
    ]
    return Result(ids, gid)


def _letter_owner(source: str) -> str:
    return next(p.name for p in config.current().persons if p.letter == source[0])


def _may_create(who: Who, parent: Goal | None, owner: str) -> None:
    """立项与拆分归 owner 角色；负责人只能在自己负责的目标下面拆给自己
    （接手一个目标后怎么做由负责人自己定，不必每拆一步都找 owner）。
    拆给别人、另开一棵目标树，仍然只有 owner 角色能做。"""
    if is_team_owner(who.person):
        return
    if parent is None:
        raise ActionError(403, t("err.create_top"))
    if parent.owner != who.person:
        raise ActionError(403, t("err.create_under_other", title=parent.title, owner=person_name(parent.owner)))
    if owner != who.person:
        raise ActionError(403, t("err.create_for_other"))


def _next_seq(b: Board, parent_id: int) -> int:
    """这一块在上层下的号：数一数曾经挂到这个上层下的块（含后来撤掉、挪走的），加一。号发出去就不变。"""
    used = sum(1 for e in b.by_id.values()
               if (e.kind == "goal.proposed" or (e.kind == "goal.edited" and "parent_id" in e.payload))
               and e.payload.get("parent_id") == parent_id)
    return used + 1


def _not_before_parent(parent: Goal, at: datetime) -> None:
    """上层目标先有，才拆得出下层（时间线上业务目标不能比它拆出来的事还晚）。"""
    if at < parent.approved_at:
        raise ActionError(409, t("err.before_parent", title=parent.title, time=tz_text(parent.approved_at),
                                 tz=tz_note()))


def _assign(conn, b, params, who, now, occ) -> Result:
    _need_team_owner(who)
    p = _P(params, _keys("assign"))
    g, now_g = _goal_then(b, p.integer("goal_id"), occ)
    owner = p.choice("owner", people())
    _need_status(g, "approved", "active", at=_then(g, now_g, occ))
    if owner == g.owner:
        raise ActionError(409, t("err.owner_unchanged"))
    return Result([_emit(conn, f"goal:{g.id}", "goal.assigned", {"owner": owner}, who, now, occ)], g.id)


def _start_stage(conn, b, params, who, now, occ) -> Result:
    p = _P(params, _keys("start_stage"))
    g, now_g = _goal_then(b, p.integer("goal_id"), occ)
    stage = p.choice("stage", stages())
    # 替别人做环节的人（比如一位同事替负责人测试）可以自己记这一段的起止，但只限自己做的那段；
    # 目标的其他事仍归负责人或 owner 角色。权限按现在的负责人算
    manager = who.person == now_g.owner or is_team_owner(who.person)
    executor = p.choice("executor", people(), required=False) or (g.owner if manager else who.person)
    if not manager and executor != who.person:
        raise ActionError(403, t("err.stage_for_other", owner=person_name(now_g.owner)))
    _need_status(g, "approved", "active", at=_then(g, now_g, occ))     # 目标完成后不再补环节
    if not g.owner:
        raise ActionError(409, t("err.assign_first"))
    if g.running(stage):
        raise ActionError(409, t("err.stage_running", stage=stage, at=_at(g, now_g, occ)))
    eid = _emit(conn, f"goal:{g.id}", "stage.started", {"stage": stage, "executor": executor}, who, now, occ)
    return Result([eid], g.id)


def _end_stage(conn, b, params, who, now, occ) -> Result:
    p = _P(params, _keys("end_stage"))
    g, now_g = _goal_then(b, p.integer("goal_id"), occ)
    stage = p.choice("stage", stages())
    span = g.running(stage)                 # 那一刻在进行的那段：结束时刻自然不早于它的开始
    if span is None:
        raise ActionError(409, t("err.stage_not_running", stage=stage, at=_at(g, now_g, occ)))
    if who.person != span.executor:         # 自己做的那段自己能结束；别人的段要负责人或 owner 角色
        _need_owner(now_g, who)
    return Result([_emit(conn, f"goal:{g.id}", "stage.ended", {"stage": stage}, who, now, occ)], g.id)


def _remove_dependency(conn, b, params, who, now, occ) -> Result:
    p = _P(params, _keys("remove_dependency"))
    g, now_g = _goal_then(b, p.integer("goal_id"), occ)
    on = p.integer("on_goal")
    _need_owner(now_g, who)
    if not any(d.on_goal == on for d in g.deps):
        raise ActionError(404, t("err.no_such_dep"))
    return Result([_emit(conn, f"goal:{g.id}", "dep.removed", {"on_goal": on}, who, now, occ)], g.id)


def _edit_goal(conn, b, params, who, now, occ) -> Result:
    p = _P(params, _keys("edit_goal"))
    then_g, g = _goal_then(b, p.integer("goal_id"), occ)     # 改名、改说明、挂版本可以补在任何位置；结构按现在校验
    _need_owner(g, who)
    payload: dict = {}
    if p.text("title", required=False, max_len=80):
        payload["title"] = p.text("title", max_len=80)
    # 页面「改概要」表单两栏一起交：没动的那栏不记，不然留痕里每次都多一条「已更新」
    if "note" in params and (note := p.text("note", required=False, max_len=500)) != g.note:
        payload["note"] = note
    if "done_what" in params and (done_what := p.text("done_what", required=False, max_len=DONE_WHAT_MAX)) != g.done_what:
        # 按那一刻的状态：补在完成之前的会被重放时的「完成」盖掉，接口报成功却不生效
        if done_what and then_g.status != "done":
            raise ActionError(409, t("err.done_what_early", gnum=g.gnum, then=t("when.then_short") if then_g is not g else ""))
        payload["done_what"] = done_what
    parent_raw = params.get("parent_id")
    if parent_raw not in (None, ""):
        # 挂到哪棵树下、在哪条线，等于重新立项；负责人只能动自己树内的内容，不能把拆给他的块摘成顶层
        # 或挂到别人树下
        _need_team_owner(who)
        if parent_raw == "-":
            if g.parent_id is None:
                raise ActionError(409, t("err.already_top"))
            payload["parent_id"] = None
        else:
            new_parent = _goal(b, p.integer("parent_id"))      # 整数或数字字符串都行
            if new_parent.id == g.parent_id:                     # 原地重挂不发新号
                raise ActionError(409, t("err.already_under", gnum=new_parent.gnum, title=new_parent.title))
            node: Goal | None = new_parent
            while node is not None:          # 不能挂到自己或自己的下层下面
                if node.id == g.id:
                    raise ActionError(409, t("err.cycle"))
                node = b.goals.get(node.parent_id) if node.parent_id is not None else None
            _not_before_parent(new_parent, g.approved_at)
            if new_parent.sample != g.sample:
                raise ActionError(409, t("err.sample_mix_parent"))
            payload["parent_id"] = new_parent.id
            payload["seq"] = _next_seq(b, new_parent.id)
    if p.text("line", required=False):
        _need_team_owner(who)
        line = p.choice("line", lines())
        if line == g.line:
            raise ActionError(409, t("err.same_line", line=line))
        payload["line"] = line
    version = p.text("version", required=False)
    if version:
        if version != "-":
            _version_ref(version)
        payload["version"] = None if version == "-" else version
    if "long_term" in params:
        long_term = p.flag("long_term")
        if long_term and g.latest_due is not None:
            raise ActionError(409, t("err.long_term_has_due"))
        if long_term == g.long_term:
            raise ActionError(409, t("err.long_term_unchanged"))
        payload["long_term"] = long_term
    if str(params.get("source") or "").strip():
        if not is_team_owner(who.person):
            raise ActionError(403, t("err.source_owner_only"))
        if g.source:
            raise ActionError(409, t("err.source_fixed", gnum=g.gnum, source=g.source))
        payload["source"] = _source(b, params["source"])
    if not payload:
        raise ActionError(400, t("err.nothing_to_change"))
    return Result([_emit(conn, f"goal:{g.id}", "goal.edited", payload, who, now, occ)], g.id)


def _add_note(conn, b, params, who, now, occ) -> Result:
    p = _P(params, _keys("add_note"))
    text = p.text("text", max_len=4000)
    gid = p.integer("goal_id", required=False)
    if gid is not None:
        _goal(b, gid)
    payload = {"text": text, **({"goal_id": gid} if gid is not None else {})}
    return Result([_emit(conn, "inbox", "note.added", payload, who, now, occ)])


def _resolve_note(conn, b, params, who, now, occ) -> Result:
    p = _P(params, _keys("resolve_note"))
    nid, summary = p.integer("note_id"), p.text("summary", max_len=500)
    note = b.notes.get(nid)
    if note is None:
        raise ActionError(404, t("err.no_note", id=nid))
    if note.resolved_at is not None:
        raise ActionError(409, t("err.note_resolved"))
    return Result([_emit(conn, "inbox", "note.resolved", {"note_id": nid, "summary": summary}, who, now, occ)])


def _void(conn, b, params, who, now, occ) -> Result:
    p = _P(params, _keys("void"))
    eid, reason = p.integer("event_id"), p.text("reason", max_len=200)
    target = b.by_id.get(eid)
    if target is None:
        raise ActionError(404, t("err.no_event", id=eid))
    if target.kind == "event.voided" or eid in b.voided:
        raise ActionError(409, t("err.already_voided"))
    if who.person != target.actor and not is_team_owner(who.person):
        raise ActionError(403, t("err.void_not_yours"))
    if target.kind == "goal.proposed":
        # 撤掉整个目标：只允许刚建好、还没有后续记录（立项、指派是建目标时一起写的）
        # 「一起写的」只算建目标那一批（同一记录时刻）的立项/指派；事后的改派算后续记录
        others = [e for e in b.by_id.values() if e.subject == target.subject and e.id != eid
                  and not (e.kind in ("goal.approved", "goal.assigned") and e.recorded_at == target.recorded_at)
                  and e.kind != "event.voided" and e.id not in b.voided]
        gid = int(target.subject[5:])
        g = b.goals.get(gid)
        if others or (g is not None and g.children):
            raise ActionError(409, t("err.void_has_records"))
        # 别的目标还依赖它、或暂停等它时不能撤，否则页面找不到它会整站打不开
        users = [x for x in b.goals.values() if x.id != gid
                 and (any(d.on_goal == gid for d in x.deps) or any(ps.depends_on == gid for ps in x.pauses))]
        if users:
            names = _sep().join(t("goal.ref", gnum=x.gnum, title=x.title) for x in users)
            raise ActionError(409, t("err.void_depended", names=names))
    return Result([_emit(conn, target.subject, "event.voided", {"event_id": eid, "reason": reason},
                         who, now, occ)])


def _pause(conn, b, params, who, now, occ) -> Result:
    p = _P(params, _keys("pause"))
    g, now_g = _goal_then(b, p.integer("goal_id"), occ)
    kind = p.choice("kind", PAUSE_KEYS)
    dep = p.integer("depends_on", required=False)
    note = p.text("note", required=False, max_len=200)
    _need_owner(now_g, who)
    _need_status(g, "approved", "active", at=_then(g, now_g, occ))
    if g.current_pause:
        raise ActionError(409, t("err.already_paused"))
    if any(ps.start > occ for ps in now_g.pauses):   # 暂停段不交错：后面已有暂停就不能往前插
        raise ActionError(409, t("err.pause_after_last"))
    if kind == "dependency":
        if dep is None:
            raise ActionError(400, t("err.pause_needs_goal"))
        if _goal(b, dep).id == g.id:
            raise ActionError(400, t("err.wait_self"))
        if b.goals[dep].sample != g.sample:
            raise ActionError(409, t("err.sample_mix_wait"))
    elif dep is not None:
        raise ActionError(400, t("err.depends_only_dependency"))
    eid = _emit(conn, f"goal:{g.id}", "pause.started",
                {"kind": kind, "depends_on": dep, "note": note}, who, now, occ)
    return Result([eid], g.id)


def _resume(conn, b, params, who, now, occ) -> Result:
    p = _P(params, _keys("resume"))
    g, now_g = _goal_then(b, p.integer("goal_id"), occ)
    _need_owner(now_g, who)
    if not g.current_pause:
        raise ActionError(409, t("err.not_paused", at=_at(g, now_g, occ)))
    return Result([_emit(conn, f"goal:{g.id}", "pause.ended", {}, who, now, occ)], g.id)


def _change_due(conn, b, params, who, now, occ) -> Result:
    p = _P(params, _keys("change_due"))
    g, now_g = _goal_then(b, p.integer("goal_id"), occ)
    due, reason = p.due("due"), p.text("reason", max_len=200)
    _need_owner(now_g, who)
    _need_status(g, "approved", "active", at=_then(g, now_g, occ))
    if g.long_term:
        raise ActionError(409, t("err.long_term_no_due"))
    if g.latest_due is not None and due == str(g.latest_due):  # 没有基准日时这里为 None，直接成为基准
        raise ActionError(409, t("err.same_due"))
    eid = _emit(conn, f"goal:{g.id}", "due.changed", {"due": due, "reason": reason}, who, now, occ)
    return Result([eid], g.id)


def _declare_dependency(conn, b, params, who, now, occ) -> Result:
    p = _P(params, _keys("declare_dependency"))
    g, now_g = _goal_then(b, p.integer("goal_id"), occ)
    on = _goal(b, p.integer("on_goal"))
    at_stage, need_by = p.choice("at_stage", stages()), p.due("need_by", required=False)
    _need_owner(now_g, who)
    _need_status(g, "approved", "active", at=_then(g, now_g, occ))
    if on.id == g.id:
        raise ActionError(400, t("err.depend_self"))
    if on.sample != g.sample:
        raise ActionError(409, t("err.sample_mix_dep"))
    if any(d.on_goal == on.id for d in g.deps):
        raise ActionError(409, t("err.dep_exists"))
    eid = _emit(conn, f"goal:{g.id}", "dep.declared",
                {"on_goal": on.id, "at_stage": at_stage, "need_by": need_by or None}, who, now, occ)
    return Result([eid], g.id)


def _link_issue(conn, b, params, who, now, occ) -> Result:
    p = _P(params, _keys("link_issue"))
    g, now_g = _goal_then(b, p.integer("goal_id"), occ)
    repo, number = p.choice("repo", repos()), p.integer("number")
    kind = p.choice("kind", ("link", "subcontract"))
    _need_owner(now_g, who)
    _need_status(g, "approved", "active", at=_then(g, now_g, occ))
    if any((x.repo, x.number) == (repo, number) for x in g.links):
        raise ActionError(409, t("err.issue_linked"))
    eid = _emit(conn, f"goal:{g.id}", "issue.linked",
                {"repo": repo, "number": number, "kind": kind}, who, now, occ)
    return Result([eid], g.id)


def _unlink_issue(conn, b, params, who, now, occ) -> Result:
    p = _P(params, _keys("unlink_issue"))
    g, now_g = _goal_then(b, p.integer("goal_id"), occ)
    repo, number = p.choice("repo", repos()), p.integer("number")
    _need_owner(now_g, who)
    if not any((x.repo, x.number) == (repo, number) for x in g.links):
        raise ActionError(404, t("err.issue_not_linked"))
    eid = _emit(conn, f"goal:{g.id}", "issue.unlinked", {"repo": repo, "number": number},
                who, now, occ)
    return Result([eid], g.id)


def _complete(conn, b, params, who, now, occ) -> Result:
    p = _P(params, _keys("complete"))
    g = _goal(b, p.integer("goal_id"))
    _need_owner(g, who)
    _need_status(g, "approved", "active")
    if g.current_pause:
        raise ActionError(409, t("err.paused_resume_first"))
    if any(b.goals[c].status not in _ENDED for c in g.children):
        raise ActionError(409, t("err.children_open"))
    # 上层目标靠下层做成，不能记成比下层还早完成（补录也不能绕过）
    last = max((b.goals[c] for c in g.children if b.goals[c].closed_at), key=lambda c: c.closed_at, default=None)
    if last is not None and occ < last.closed_at:
        raise ActionError(409, t("err.parent_before_child", gnum=last.gnum, title=last.title,
                                 time=tz_text(last.closed_at), tz=tz_note()))
    _after_all_records(g, occ)
    done_what = p.text("done_what", required=False, max_len=DONE_WHAT_MAX)
    return Result([_emit(conn, f"goal:{g.id}", "goal.completed", {"done_what": done_what} if done_what else {}, who, now, occ)], g.id)


def _abandon(conn, b, params, who, now, occ) -> Result:
    _need_team_owner(who)
    p = _P(params, _keys("abandon"))
    g = _goal(b, p.integer("goal_id"))
    reason = p.text("reason", max_len=200)
    if g.status in _ENDED:
        raise ActionError(409, t("err.goal_ended"))
    _after_all_records(g, occ)
    eid = _emit(conn, f"goal:{g.id}", "goal.abandoned", {"reason": reason}, who, now, occ)
    return Result([eid], g.id)


def _track_version(conn, b, params, who, now, occ) -> Result:
    p = _P(params, _keys("track_version"))
    ref = p.text("ref")
    repo, number = _version_ref(ref)
    if ref in b.versions:
        raise ActionError(409, t("err.version_tracked"))
    ids = [_emit(conn, f"version:{ref}", "version.tracked", {}, who, now, occ)]
    row = conn.execute("SELECT due_on FROM gh_milestones WHERE repo=? AND number=?",
                       (repo, number)).fetchone()
    if row and row["due_on"]:
        # 第一次关注时，GitHub 上有截止日就预填成计划
        ids.append(_emit(conn, f"version:{ref}", "version.planned",
                         {"due": str(gh_due_day(parse_ts(row["due_on"]))), "source": "github"},
                         who, now, occ))
    return Result(ids)


def _plan_version(conn, b, params, who, now, occ) -> Result:
    _need_team_owner(who)
    p = _P(params, _keys("plan_version"))
    ref, due = p.text("ref"), p.due("due")
    vt_now = b.versions.get(ref)
    if vt_now is None:
        raise ActionError(404, t("err.version_track_first"))
    vt = _as_of(b, occ).versions.get(ref)
    if vt is None:
        raise ActionError(409, t("err.version_before_tracked", time=tz_text(vt_now.tracked_at), tz=tz_note()))
    if vt.latest is not None and str(vt.latest) == due:
        raise ActionError(409, t("err.version_same_due"))
    return Result([_emit(conn, f"version:{ref}", "version.planned", {"due": due, "source": "board"},
                         who, now, occ)])


def _complete_version(conn, b, params, who, now, occ) -> Result:
    p = _P(params, _keys("complete_version"))
    ref = p.text("ref")
    vt = b.versions.get(ref)
    if vt is None:
        raise ActionError(404, t("err.version_untracked"))
    _after_version(vt, occ)
    if vt.done_at is not None:
        raise ActionError(409, t("err.version_done"))
    return Result([_emit(conn, f"version:{ref}", "version.completed", {}, who, now, occ)])


def _link_weekly(conn, b, params, who, now, occ) -> Result:
    p = _P(params, _keys("link_weekly"))
    week, url = p.day("week_start"), p.text("url", max_len=500)
    if parse_day(week).weekday() != 0:
        raise ActionError(400, t("err.week_monday"))
    if not url.startswith("https://"):
        raise ActionError(400, t("err.url_https"))
    return Result([_emit(conn, "board", "weekly.linked", {"week_start": week, "url": url},
                         who, now, occ)])


_HANDLERS: dict[str, Handler] = {
    "create": _create, "assign": _assign, "start_stage": _start_stage, "end_stage": _end_stage,
    "remove_dependency": _remove_dependency, "edit_goal": _edit_goal,
    "add_note": _add_note, "resolve_note": _resolve_note, "void": _void, "pause": _pause, "resume": _resume, "change_due": _change_due,
    "declare_dependency": _declare_dependency, "link_issue": _link_issue,
    "unlink_issue": _unlink_issue, "complete": _complete, "abandon": _abandon,
    "track_version": _track_version, "plan_version": _plan_version,
    "complete_version": _complete_version, "link_weekly": _link_weekly,
}
ACTIONS: tuple[str, ...] = tuple(_HANDLERS)


def apply_action(conn: sqlite3.Connection, action: str, params: dict, who: Who,
                 now: datetime) -> Result:
    handler = _HANDLERS.get(action)
    if handler is None:
        raise ActionError(400, t("err.no_action", action=action))
    if who.person not in people():
        raise ActionError(403, t("err.not_on_roster"))
    if not isinstance(params, dict):
        raise ActionError(400, t("err.params_object"))
    if action in GITHUB_ACTIONS and not repos():
        raise ActionError(400, t("err.github_off"))
    raw = params.get("occurred_at")
    try:
        occ = parse_ts(raw) if raw else now
    except (TypeError, ValueError):
        raise ActionError(400, t("err.occurred_at")) from None
    if occ > now + FUTURE_TOLERANCE:
        raise ActionError(400, t("err.future"))
    # 所有写入共用写锁；先锁后读，避免两个入口检查同一旧状态后各自追加。
    if not conn.in_transaction:
        conn.execute("BEGIN IMMEDIATE")
    try:
        board = fold(load_events(conn))
        result = handler(conn, board, params, who, now, occ)
        # 提交前在同一个事务里重算一遍：事件只追加、删不掉，任何「写进去就算不出状态」
        # 的记录都必须在这里拦下，否则整个看板会永久打不开
        try:
            fold(load_events(conn))
        except ValueError as e:
            raise ActionError(409, t("err.inconsistent", detail=e)) from e
        except Exception as e:  # noqa: BLE001
            raise ActionError(409, t("err.unfoldable", kind=type(e).__name__)) from e
    except Exception:
        conn.rollback()
        raise
    conn.commit()
    return result
