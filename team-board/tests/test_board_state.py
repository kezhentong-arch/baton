import os
import time
from datetime import datetime, timedelta, timezone
from itertools import count

import pytest

from team_board.board.state import (blamed_children, delay, dependency_warnings, fold, handoffs,
                             pause_days, stage_days, stage_spans)

ON, OFF = "stage.started", "stage.ended"
from team_board.board.store import Event

T0 = datetime(2026, 9, 1, 17, 0, tzinfo=timezone.utc)   # 洛杉矶 09-01 10:00
_ids = count(1)


def ev(gid, event_kind, day, actor="linxia", **p):
    # 参数别叫 kind：暂停事件的 payload 自己就有 kind 字段
    return Event(next(_ids), f"goal:{gid}", event_kind, p, actor, "web",
                 T0 + timedelta(days=day), T0, False)


def goal(gid=1, due="2026-09-10", owner="linxia", parent=None):
    return [ev(gid, "goal.proposed", 0, title=f"G{gid}", line="增长", parent_id=parent,
               version=None, sample=False, note=""),
            ev(gid, "goal.approved", 0, baseline_due=due),
            ev(gid, "goal.assigned", 0, owner=owner, entry_stage="产品")]


def test_stage_days_exclude_pauses():
    evs = goal() + [
        ev(1, ON, 0, stage="产品", executor="linxia"),
        ev(1, OFF, 2, stage="产品"),
        ev(1, ON, 2, stage="开发", executor="linxia"),
        ev(1, "pause.started", 3, kind="external", depends_on=None, note=""),
        ev(1, "pause.ended", 5),
        ev(1, OFF, 6, stage="开发"),
        ev(1, ON, 6, stage="产品", executor="linxia"),     # 测出问题回头改产品
        ev(1, OFF, 7, stage="产品"),
        ev(1, ON, 7, stage="开发", executor="linxia"),
    ]
    g = fold(evs).goals[1]
    now = T0 + timedelta(days=9)
    assert stage_days(g, now) == {"业务": 0.0, "产品": 3.0, "UI": 0.0, "开发": 4.0, "测试": 0.0}
    assert pause_days(g, now)["external"] == 2.0


@pytest.mark.parametrize("tz", ["Asia/Shanghai", "America/Los_Angeles"])
def test_delay_ignores_host_timezone(tz):
    old = os.environ.get("TZ")
    os.environ["TZ"] = tz
    time.tzset()
    try:
        evs = goal(due="2026-09-10") + [
            ev(1, ON, 0, stage="产品", executor="linxia"),
            ev(1, "goal.completed", 11),      # 2026-09-12 10:00 洛杉矶
        ]
        g = fold(evs).goals[1]
        assert delay(g, T0 + timedelta(days=20)) == (1.42, 0.0)   # 09-10 23:59 到 09-12 10:00 实际超出 1 天 10 小时（不向上取整）
    finally:
        if old is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = old
        time.tzset()


def test_parent_blames_late_child_and_dependency_warns():
    evs = goal(1, due="2026-09-20") + goal(2, due="2026-09-15", parent=1) \
        + goal(3, due="2026-09-25", owner="zhouxing", parent=1) + [
            ev(2, "dep.declared", 1, on_goal=3, at_stage="开发", need_by=None),
        ]
    b = fold(evs)
    assert blamed_children(b.goals[1], b, T0 + timedelta(days=2)) == [3]
    assert dependency_warnings(b, T0 + timedelta(days=2)) == [
        (2, 3, "等的「G3」预计 2026-09-25 完成，晚于需要它的 2026-09-15")]
    assert handoffs(b.goals[3], b) == 1      # 业务交给周行


def test_version_stage_spans_cover_first_in_to_last_out():
    evs = goal(1) + goal(2) + [
        ev(1, ON, 1, stage="开发", executor="linxia"),
        ev(1, OFF, 4, stage="开发"),
        ev(1, ON, 4, stage="测试", executor="linxia"),
        ev(2, ON, 2, stage="开发", executor="linxia"),
        ev(2, OFF, 6, stage="开发"),
        ev(2, ON, 6, stage="测试", executor="linxia"),
    ]
    b = fold(evs)
    spans = stage_spans([b.goals[1], b.goals[2]], T0 + timedelta(days=8))
    assert spans["开发"] == (T0 + timedelta(days=1), T0 + timedelta(days=6))
    assert spans["测试"] == (T0 + timedelta(days=4), T0 + timedelta(days=8))
    assert spans["产品"] is None


def test_parallel_and_repeated_stages_each_counted():
    evs = goal() + [
        ev(1, ON, 0, stage="产品", executor="linxia"),
        ev(1, ON, 1, stage="UI", executor="linxia"),       # 和产品同时进行
        ev(1, OFF, 3, stage="产品"),
        ev(1, ON, 3, stage="开发", executor="linxia"),
        ev(1, OFF, 4, stage="UI"),
        ev(1, ON, 6, stage="产品", executor="linxia"),     # 测出问题回头改产品，开发同时继续
        ev(1, OFF, 7, stage="产品"),
    ]
    g = fold(evs).goals[1]
    now = T0 + timedelta(days=8)
    assert stage_days(g, now) == {"业务": 0.0, "产品": 4.0, "UI": 3.0, "开发": 5.0, "测试": 0.0}
    assert [s.stage for s in g.open_spans] == ["开发"]


def test_voided_events_are_ignored_and_inconsistent_voids_raise():
    evs = goal() + [ev(1, ON, 1, stage="产品", executor="linxia"),
                    ev(1, OFF, 2, stage="产品")]
    start_id, end_id = evs[-2].id, evs[-1].id
    voided_end = evs + [Event(next(_ids), "goal:1", "event.voided", {"event_id": end_id, "reason": "录错"},
                              "linxia", "web", T0 + timedelta(days=3), T0, False)]
    g = fold(voided_end).goals[1]
    assert [s.stage for s in g.open_spans] == ["产品"]          # 结束被作废，产品仍在进行
    bad = evs + [Event(next(_ids), "goal:1", "event.voided", {"event_id": start_id, "reason": "录错"},
                       "linxia", "web", T0 + timedelta(days=3), T0, False)]
    with pytest.raises(ValueError):                              # 作废了开始，后面的结束就对不上
        fold(bad)


def test_baseline_can_be_set_after_approval():
    evs = [ev(1, "goal.proposed", 0, title="G", line="管理与协作", parent_id=None, version=None,
              sample=False, note=""),
           ev(1, "goal.approved", 0, baseline_due=None),
           ev(1, "due.changed", 2, due="2026-09-20", reason="周会定了"),
           ev(1, "due.changed", 5, due="2026-09-25", reason="延一周")]
    g = fold(evs).goals[1]
    assert str(g.baseline_due) == "2026-09-20" and str(g.latest_due) == "2026-09-25"


def _void(target_id, day):
    return Event(next(_ids), "goal:1", "event.voided", {"event_id": target_id, "reason": "录错"},
                 "linxia", "web", T0 + timedelta(days=day), T0, False)


def test_voiding_the_creation_withdraws_the_whole_goal():
    evs = goal()
    g_ids = [e.id for e in evs]
    b = fold(evs + [_void(g_ids[0], 1)])
    assert 1 not in b.goals


def test_same_line_children_follow_a_line_change_cross_line_ones_stay():
    """换线时同线的下层跟着走；拆到别的线上的块留在原地；挂到别的上层下面不改自己的线。"""
    evs = goal(1) + goal(2, parent=1) + goal(3, parent=2) + goal(4) + [
        ev(5, "goal.proposed", 0, title="跨线块", line="运营", parent_id=1, version=None, note="", sample=False),
        ev(1, "goal.edited", 1, line="管理与协作"),
    ]
    b = fold(evs)
    assert {b.goals[i].line for i in (1, 2, 3)} == {"管理与协作"} and b.goals[4].line == "增长"
    assert b.goals[5].line == "运营" and b.goals[5].parent_id == 1
    b = fold(evs + [ev(4, "goal.edited", 2, parent_id=1)])
    assert b.goals[4].line == "增长" and b.goals[1].children == [2, 5, 4]
