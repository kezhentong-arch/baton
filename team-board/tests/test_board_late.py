"""延期从现在的计划（最后一次定的）算：改了期、新日期没到不算延期，过了才从新日期算；长期行、放弃的不算。
写出来的字和个人看板一字不差（个人看板 tests/test_late_rule.py 是同一组用例）。延期里「等外部」只算计划之后那段。
版本同样从现在的计划算。"""
from datetime import date, datetime, timedelta, timezone
from itertools import count

import pytest

from team_board.board.actions import Who, apply_action
from team_board.board.issues import GhData
from team_board.board.state import delay, delay_text, fold, late_external
from team_board.board.store import Event, connect_board, load_events
from team_board.board.timeline import Scale, _goal_row, _version_row
from team_board.board.view import blockers, build_goal, build_version

T0 = datetime(2026, 9, 1, 17, 0, tzinfo=timezone.utc)   # 洛杉矶 09-01 10:00
_ids = count(1)

# (说明, 计划们（立项定的、之后每次改的）, 完成, 放弃, 长期, 现在, 期望的字)；时刻都是洛杉矶带时差的写法
CASES = [
    ("没改过期、过了", ["2026-09-10"], None, None, False, "2026-09-12T10:00:00-07:00", "1.4 天"),
    ("改过期、新日期没到", ["2026-09-10", "2026-09-20"], None, None, False, "2026-09-12T10:00:00-07:00", ""),
    ("改过期、新日期也过了", ["2026-09-10", "2026-09-20"], None, None, False, "2026-09-22T10:00:00-07:00", "1.4 天"),
    ("改了两次、按最后一次", ["2026-09-10", "2026-09-30", "2026-09-20"], None, None, False, "2026-09-22T10:00:00-07:00", "1.4 天"),
    ("改过期、新日期前做完", ["2026-09-10", "2026-09-20"], "2026-09-15T10:00:00-07:00", None, False, "2026-09-25T10:00:00-07:00", ""),
    ("改过期、新日期后做完", ["2026-09-10", "2026-09-20"], "2026-09-21T10:00:00-07:00", None, False, "2026-09-25T10:00:00-07:00", "10 小时"),
    ("改早了也照算", ["2026-09-10", "2026-09-08 08:00"], None, None, False, "2026-09-08T11:30:00-07:00", "4 小时"),
    ("放弃的不算", ["2026-09-10", "2026-09-12"], None, "2026-09-20T10:00:00-07:00", False, "2026-09-25T10:00:00-07:00", ""),
    ("长期行带着计划也不算", ["2026-09-10"], None, None, True, "2026-09-12T10:00:00-07:00", ""),
    ("夏令时结束日写到小时", ["2026-11-01 10:00"], None, None, False, "2026-11-01T11:30:00-08:00", "2 小时"),
    ("夏令时结束日只写日期", ["2026-11-01"], None, None, False, "2026-11-02T10:00:00-08:00", "10 小时"),
    ("夏令时结束日重复的钟点取第一次", ["2026-11-01 01:30"], None, None, False, "2026-11-01T01:30:00-08:00", "1 小时"),
    ("夏令时开始日只写日期", ["2027-03-14"], None, None, False, "2027-03-15T10:00:00-07:00", "10 小时"),
    ("夏令时开始日写到小时", ["2027-03-14 03:30"], None, None, False, "2027-03-14T06:00:00-07:00", "3 小时"),
    ("夏令时开始日跳过的钟点按冬令时", ["2027-03-14 02:30"], None, None, False, "2027-03-14T05:00:00-07:00", "2 小时"),
]


def _at(s: str) -> datetime:
    return datetime.fromisoformat(s).astimezone(timezone.utc)   # 库里、接口传进来的时刻都是 UTC


def _ev(event_kind, at, **p):
    # 参数别叫 kind：暂停事件的 payload 自己就有 kind 字段
    return Event(next(_ids), "goal:1", event_kind, p, "linxia", "web", at, at, False)


def _goal(dues, done=None, abandoned=None, long_term=False, pauses=()):
    """立项定 dues[0]，09-05 起每天改一次期；pauses 是 (起, 止) 的等外部暂停（带时差的写法）。"""
    evs = [_ev("goal.proposed", T0, title="G1", line="增长", parent_id=None, version=None, sample=False, note="",
               long_term=long_term),
           _ev("goal.approved", T0, baseline_due=dues[0]),
           _ev("goal.assigned", T0, owner="linxia", entry_stage="产品"),
           _ev("stage.started", T0, stage="产品", executor="linxia")]
    evs += [_ev("due.changed", T0 + timedelta(days=4 + i), due=d, reason="改期") for i, d in enumerate(dues[1:])]
    for a, b in pauses:
        evs += [_ev("pause.started", _at(a), kind="external", depends_on=None, note=""), _ev("pause.ended", _at(b))]
    if done:
        evs.append(_ev("goal.completed", _at(done)))
    if abandoned:
        evs.append(_ev("goal.abandoned", _at(abandoned), reason="不做了"))
    return fold(sorted(evs, key=lambda e: (e.occurred_at, e.id))).goals[1]


@pytest.mark.parametrize("c", CASES, ids=[c[0] for c in CASES])
def test_delay_counts_from_current_plan(c):
    _what, dues, done, abandoned, long_term, now, want = c
    g = _goal(dues, done, abandoned, long_term)
    assert delay_text(g, _at(now)) == want
    assert (delay(g, _at(now))[0] > 0) == bool(want)


def test_external_wait_only_counts_after_current_plan():
    """等外部只算现在的计划之后那段：拿全部等外部的总时长，改期后会写出「已超出 10 小时（其中等外部 6 天）」。"""
    before = _goal(["2026-09-10", "2026-09-20"], pauses=[("2026-09-05T10:00:00-07:00", "2026-09-11T10:00:00-07:00")])
    now = _at("2026-09-21T10:00:00-07:00")
    assert delay_text(before, now) == "10 小时" and late_external(before, now) == timedelta(0) and delay(before, now)[1] == 0.0
    after = _goal(["2026-09-10"], pauses=[("2026-09-11T10:00:00-07:00", "2026-09-12T10:00:00-07:00")])
    now = _at("2026-09-13T10:00:00-07:00")
    assert late_external(after, now) == timedelta(days=1) and delay(after, now) == (2.42, 1.0)
    across = _goal(["2026-09-10"], pauses=[("2026-09-10T12:00:00-07:00", "2026-09-11T12:00:00-07:00")])   # 跨过计划那一刻
    assert late_external(across, now) == timedelta(hours=12, seconds=1)
    running = _goal(["2026-09-10"], pauses=[("2026-09-12T10:00:00-07:00", "2026-09-12T10:00:00-07:00")])
    running.pauses[-1].end = None                         # 还在等：算到现在
    assert late_external(running, now) == timedelta(days=1)


def test_external_wait_text_on_blocker_and_goal_page(tmp_path):
    """卡点和详情页写的「其中等外部」也只算计划之后那段。"""
    conn = connect_board(tmp_path)
    me = Who("linxia", "web")
    gid = apply_action(conn, "create", {"title": "等外部的事", "line": "增长", "owner": "linxia", "due": "2026-09-10",
                                        "occurred_at": "2026-09-01T10:00:00-07:00"}, me, T0).goal_id
    for action, extra, at in (("pause", {"kind": "external"}, "2026-09-05T10:00:00-07:00"),
                              ("resume", {}, "2026-09-11T10:00:00-07:00"),
                              ("change_due", {"due": "2026-09-20", "reason": "改期"}, "2026-09-12T10:00:00-07:00")):
        apply_action(conn, action, {"goal_id": gid, **extra, "occurred_at": at}, me, T0 + timedelta(days=20))
    b, now = fold(load_events(conn)), _at("2026-09-21T10:00:00-07:00")
    text = next(x.text for x in blockers(b, GhData(conn), now) if x.key == "late")
    assert text.endswith("已超出计划 10 小时")                       # 不写「（其中等外部 6 天）」
    d = build_goal(conn, b, b.goals[gid], now, me)
    assert d["delay_text"] == "10 小时" and d["external"] == ""


def test_replanned_row_draws_current_plan_and_grey_original():
    """时间线：主计划线画在现在的计划，最早那条是灰色「原计划」；新日期没到不画红框，过了从新日期起画。"""
    g = _goal(["2026-09-10", "2026-09-20"])
    sc = Scale(date(2026, 9, 1), date(2026, 9, 30))
    row = _goal_row(g, _at("2026-09-12T10:00:00-07:00"), sc, 0)
    assert [(m.label, m.orig) for m in row.marks] == [("计划 09-20", False), ("原计划 09-10", True)]
    assert row.overflow is None and row.late == ""
    row = _goal_row(g, _at("2026-09-22T10:00:00-07:00"), sc, 0)
    assert row.overflow[0] == row.marks[0].x and row.late == "1.4 天"
    plain = _goal_row(_goal(["2026-09-10"]), _at("2026-09-12T10:00:00-07:00"), sc, 0)
    assert [(m.label, m.orig) for m in plain.marks] == [("计划 09-10", False)] and plain.late == "1.4 天"


def test_long_term_row_draws_no_plan_or_overflow():
    """长期行即使带着计划（作废记录才造得出来）也不画计划线和红框，同个人看板。"""
    g = _goal(["2026-09-10"], long_term=True)
    row = _goal_row(g, _at("2026-09-12T10:00:00-07:00"), Scale(date(2026, 9, 1), date(2026, 9, 30)), 0)
    assert row.marks == [] and row.overflow is None and row.late == ""


def test_version_late_counts_from_current_plan(tmp_path):
    """版本同目标：版本行、版本卡点、版本页的延期都从现在的计划算，改过期的最早那条画灰色「原计划」。"""
    conn = connect_board(tmp_path)
    me, ref = Who("linxia", "web"), "acme/app#9"
    apply_action(conn, "track_version", {"ref": ref, "occurred_at": "2026-09-01T10:00:00-07:00"}, me, T0 + timedelta(days=30))
    for due, at in (("2026-09-10", "2026-09-01T10:00:00-07:00"), ("2026-09-20", "2026-09-08T10:00:00-07:00")):
        apply_action(conn, "plan_version", {"ref": ref, "due": due, "occurred_at": at}, me, T0 + timedelta(days=30))
    b, gh = fold(load_events(conn)), GhData(conn)
    vt, sc = b.versions[ref], Scale(date(2026, 9, 1), date(2026, 9, 30))
    early, late = _at("2026-09-12T10:00:00-07:00"), _at("2026-09-22T10:00:00-07:00")
    row = _version_row(ref, vt, gh, early, sc)
    assert row.late == "" and row.overflow is None
    assert [(m.label, m.orig) for m in row.marks] == [("计划 09-20", False), ("原计划 09-10", True)]
    assert _version_row(ref, vt, gh, late, sc).late == "1.4 天"
    assert not [x for x in blockers(b, gh, early) if x.key == "version"]
    assert [x.text for x in blockers(b, gh, late) if x.key == "version"] == [f"版本 {ref}：已超出计划 1.4 天"]
    assert build_version(conn, b, "acme/app", 9, early)["late"] == ""
    assert build_version(conn, b, "acme/app", 9, late)["late"] == "1.4 天"
