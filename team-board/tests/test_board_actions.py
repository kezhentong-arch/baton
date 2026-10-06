from datetime import datetime, timedelta, timezone

import pytest

from team_board.board import actions
from team_board.board.actions import ActionError, Result, Who, apply_action
from team_board.board.state import fold
from team_board.board.store import connect_board, load_events

NOW = datetime(2026, 10, 1, 18, 0, tzinfo=timezone.utc)
LIN, ZHOU, SU = Who("linxia", "web"), Who("zhouxing", "web"), Who("suhe", "web")


@pytest.fixture
def conn(tmp_path):
    c = connect_board(tmp_path)
    yield c
    c.close()


def _create(conn, title="看板", line="管理与协作", owner="zhouxing", **extra):
    return apply_action(conn, "create", {"title": title, "line": line, "owner": owner, **extra}, LIN, NOW).goal_id


def _active_goal(conn, owner="zhouxing"):
    gid = _create(conn, owner=owner, due="2026-10-20")
    apply_action(conn, "start_stage", {"goal_id": gid, "stage": "产品"}, LIN, NOW)
    return gid


def test_only_team_owner_creates_and_reassigns_owner_moves_stage(conn):
    with pytest.raises(ActionError) as e:
        apply_action(conn, "create", {"title": "看板", "line": "管理与协作", "owner": "suhe"}, SU, NOW)
    assert e.value.status == 403
    gid = _create(conn, owner="zhouxing")
    with pytest.raises(ActionError) as e:
        apply_action(conn, "assign", {"goal_id": gid, "owner": "suhe"}, ZHOU, NOW)
    assert e.value.status == 403
    with pytest.raises(ActionError) as e:         # 替周行记他自己做的段：不行（她自己做的段能记，见下面的 helper 测试）
        apply_action(conn, "start_stage", {"goal_id": gid, "stage": "产品", "executor": "zhouxing"}, SU, NOW)
    assert e.value.status == 403
    apply_action(conn, "start_stage", {"goal_id": gid, "stage": "产品"}, ZHOU, NOW)
    apply_action(conn, "assign", {"goal_id": gid, "owner": "suhe"}, LIN, NOW)
    assert fold(load_events(conn)).goals[gid].owner == "suhe"


def test_dropped_actions_are_gone(conn):
    """做减法：提议/待立项在看板之外；切换、上线、搁置都去掉。"""
    for action in ("propose", "approve", "split", "set_stage", "launch"):
        with pytest.raises(ActionError) as e:
            apply_action(conn, action, {}, LIN, NOW)
        assert e.value.status == 400
    gid = _active_goal(conn)
    with pytest.raises(ActionError):
        apply_action(conn, "pause", {"goal_id": gid, "kind": "shelved"}, LIN, NOW)


def test_bad_input_writes_nothing(conn):
    gid = _active_goal(conn)
    before = len(load_events(conn))
    for params in ({"goal_id": gid, "stage": "上线"},
                   {"goal_id": gid, "stage": "开发", "colour": "red"},
                   {"goal_id": gid, "stage": "开发", "occurred_at": "2026-10-01T10:00"}):
        with pytest.raises(ActionError):
            apply_action(conn, "start_stage", params, LIN, NOW)
    assert len(load_events(conn)) == before


def test_backfill_must_follow_history_and_not_future(conn):
    gid = _active_goal(conn)
    with pytest.raises(ActionError) as e:                 # 立项（NOW）之前没有这个目标
        apply_action(conn, "start_stage", {"goal_id": gid, "stage": "开发",
                                           "occurred_at": "2026-09-29T10:00:00-07:00"}, LIN, NOW)
    assert e.value.status == 409 and "才立项" in e.value.message
    with pytest.raises(ActionError) as e:
        apply_action(conn, "start_stage", {"goal_id": gid, "stage": "开发",
                                           "occurred_at": (NOW + timedelta(hours=2)).isoformat()},
                     LIN, NOW)
    assert e.value.status == 400
    old = apply_action(conn, "create", {"title": "旧目标", "line": "客户端", "owner": "linxia",
                                        "occurred_at": "2026-09-28T10:00:00-07:00"}, LIN, NOW)
    assert load_events(conn)[0].id == old.event_ids[0] and load_events(conn)[0].backfill


NOW2 = datetime(2026, 10, 2, 18, 0, tzinfo=timezone.utc)


def _la(hhmmss: str, day: str = "2026-10-02") -> str:
    return f"{day}T{hhmmss}-07:00"


def test_backfill_can_be_inserted_before_later_records(conn):
    """补录允许插到任何位置，只校验和那一刻的状态一致。
    个人看板往团队看板推本来就是补录，而团队看板上常常已经有更晚的记录（改说明、挂版本、别人记的段），
    旧规则「只能补在最后一条记录之后」把正常推送挡住。一个真实出现过的顺序：
    立项 08:40:50 → 08:52 改说明 → 开发 08:57 开 → 再把产品 08:40:50–08:52 补进去。"""
    gid = apply_action(conn, "create", {"title": "看板 v1.2", "line": "管理与协作", "owner": "linxia",
                                        "occurred_at": _la("08:40:50")}, LIN, NOW2).goal_id
    apply_action(conn, "edit_goal", {"goal_id": gid, "note": "两件事", "occurred_at": _la("08:52:00")}, LIN, NOW2)
    apply_action(conn, "start_stage", {"goal_id": gid, "stage": "开发", "occurred_at": _la("08:57:01")}, LIN, NOW2)
    apply_action(conn, "start_stage", {"goal_id": gid, "stage": "产品", "occurred_at": _la("08:40:50")}, LIN, NOW2)
    apply_action(conn, "end_stage", {"goal_id": gid, "stage": "产品", "occurred_at": _la("08:52:00")}, LIN, NOW2)
    g = fold(load_events(conn)).goals[gid]
    assert [(s.stage, s.start.isoformat(), s.end.isoformat() if s.end else None) for s in g.spans] == [
        ("产品", "2026-10-02T15:40:50+00:00", "2026-10-02T15:52:00+00:00"),
        ("开发", "2026-10-02T15:57:01+00:00", None)]
    # 改说明、挂单、改期也能插到前面
    apply_action(conn, "link_issue", {"goal_id": gid, "repo": "acme/web", "number": 8,
                                      "kind": "link", "occurred_at": _la("08:45:00")}, LIN, NOW2)
    apply_action(conn, "change_due", {"goal_id": gid, "due": "2026-10-02 12:00", "reason": "立项时定的",
                                      "occurred_at": _la("08:41:00")}, LIN, NOW2)
    g = fold(load_events(conn)).goals[gid]
    assert g.links and str(g.latest_due) == "2026-10-02 12:00"


def test_backfill_checks_state_at_that_moment(conn):
    """补录只校验那一刻的状态：不早于立项、环节结束不早于它的开始、目标完成后不再补环节；
    和后面记录矛盾的（同一环节重复开始、结束两次）由提交前的整体重算拦下。"""
    gid = apply_action(conn, "create", {"title": "看板 v1.2", "line": "管理与协作", "owner": "linxia",
                                        "occurred_at": _la("08:40:50")}, LIN, NOW2).goal_id
    apply_action(conn, "start_stage", {"goal_id": gid, "stage": "开发", "occurred_at": _la("08:57:00")}, LIN, NOW2)
    apply_action(conn, "end_stage", {"goal_id": gid, "stage": "开发", "occurred_at": _la("09:54:00")}, LIN, NOW2)
    before = len(load_events(conn))
    cases = [
        ("start_stage", {"goal_id": gid, "stage": "产品", "occurred_at": _la("08:40:00")}, "才立项"),       # 立项前
        ("end_stage", {"goal_id": gid, "stage": "产品", "occurred_at": _la("08:50:00")}, "没有在进行"),     # 那时没开始
        ("start_stage", {"goal_id": gid, "stage": "开发", "occurred_at": _la("09:10:00")}, "已经在进行"),   # 那时开发正在进行
        ("end_stage", {"goal_id": gid, "stage": "开发", "occurred_at": _la("09:00:00")}, "对不上"),        # 后面 09:54 又结束一次
        ("complete", {"goal_id": gid, "occurred_at": _la("09:30:00")}, "最后一条记录"),                     # 完成要在最后
    ]
    for action, params, hint in cases:
        with pytest.raises(ActionError) as e:
            apply_action(conn, action, params, LIN, NOW2)
        assert e.value.status == 409 and hint in e.value.message, (action, e.value.message)
    assert len(load_events(conn)) == before
    apply_action(conn, "complete", {"goal_id": gid, "occurred_at": _la("10:00:21")}, LIN, NOW2)
    with pytest.raises(ActionError) as e:                 # 目标完成后不再补环节
        apply_action(conn, "start_stage", {"goal_id": gid, "stage": "测试", "occurred_at": _la("10:30:00")}, LIN, NOW2)
    assert e.value.status == 409 and "是「已完成」" in e.value.message   # 补在所有记录之后，等于现在
    with pytest.raises(ActionError) as e:                 # 完成前有别的记录时，报错说「那时」
        apply_action(conn, "link_issue", {"goal_id": gid, "repo": "acme/web", "number": 8,
                                          "kind": "link", "occurred_at": _la("10:00:30")}, LIN, NOW2 + timedelta(hours=1))
    assert "那时是「已完成」" in e.value.message or "是「已完成」" in e.value.message
    apply_action(conn, "start_stage", {"goal_id": gid, "stage": "测试", "occurred_at": _la("09:05:00")}, LIN, NOW2)
    g = fold(load_events(conn)).goals[gid]                # 完成前的环节能补，完成时自动结束
    assert g.status == "done" and g.running("测试") is None
    assert [s.stage for s in g.spans] == ["开发", "测试"]
    with pytest.raises(ActionError) as e:                 # 现在记的报错不说「那时」
        apply_action(conn, "end_stage", {"goal_id": gid, "stage": "UI"}, LIN, NOW2)
    assert e.value.message == "「UI」没有在进行"


def test_paused_goal_cannot_change_stage_or_complete(conn):
    gid = _active_goal(conn)
    apply_action(conn, "pause", {"goal_id": gid, "kind": "external", "note": "商店审核"}, ZHOU, NOW)
    with pytest.raises(ActionError) as e:
        apply_action(conn, "complete", {"goal_id": gid}, ZHOU, NOW)
    assert e.value.status == 409
    apply_action(conn, "resume", {"goal_id": gid}, ZHOU, NOW)
    apply_action(conn, "complete", {"goal_id": gid}, ZHOU, NOW)


def test_version_backfill_before_history_is_rejected_and_board_still_loads(conn):
    apply_action(conn, "track_version", {"ref": "acme/app#9"}, LIN, NOW)
    before = len(load_events(conn))
    for action, params in (("plan_version", {"ref": "acme/app#9", "due": "2026-10-20"}),
                           ("complete_version", {"ref": "acme/app#9"})):
        with pytest.raises(ActionError) as e:
            apply_action(conn, action, {**params, "occurred_at": "2026-09-20T10:00:00-07:00"}, LIN, NOW)
        assert e.value.status == 409
    assert len(load_events(conn)) == before
    assert "acme/app#9" in fold(load_events(conn)).versions
    # 计划日期能插在后面记录之前；完成仍要在最后
    later = NOW + timedelta(hours=3)
    apply_action(conn, "plan_version", {"ref": "acme/app#9", "due": "2026-10-20",
                                        "occurred_at": (NOW + timedelta(hours=2)).isoformat()}, LIN, later)
    apply_action(conn, "plan_version", {"ref": "acme/app#9", "due": "2026-10-18",
                                        "occurred_at": (NOW + timedelta(hours=1)).isoformat()}, LIN, later)
    assert [str(d) for _, d in fold(load_events(conn)).versions["acme/app#9"].plans] == ["2026-10-18", "2026-10-20"]
    with pytest.raises(ActionError) as e:
        apply_action(conn, "complete_version", {"ref": "acme/app#9",
                                                "occurred_at": (NOW + timedelta(minutes=90)).isoformat()}, LIN, later)
    assert e.value.status == 409


def test_write_that_breaks_the_board_is_rolled_back(conn, monkeypatch):
    def bad(conn_, b, params, who, now, occ):
        # 模拟今后某个操作写进一条算不出状态的记录（给不存在的目标「恢复暂停」）
        return Result([actions._emit(conn_, "goal:999", "pause.ended", {}, who, now, occ)])
    monkeypatch.setitem(actions._HANDLERS, "link_weekly", bad)
    with pytest.raises(ActionError) as e:
        apply_action(conn, "link_weekly", {}, LIN, NOW)
    assert e.value.status == 409 and load_events(conn) == []


def test_board_has_no_priority_any_more(conn):
    """团队看板不设优先级——立项不收优先级，也没有调整优先级的操作。"""
    with pytest.raises(ActionError) as e:
        apply_action(conn, "create", {"title": "看板", "line": "管理与协作", "owner": "linxia",
                                      "priority": "P1"}, LIN, NOW)
    assert e.value.status == 400
    gid = _create(conn)
    with pytest.raises(ActionError):
        apply_action(conn, "set_priority", {"goal_id": gid, "priority": "P1", "reason": "x"}, LIN, NOW)


def test_stages_start_and_end_independently(conn):
    gid = _active_goal(conn)                      # 产品已在进行（_active_goal 里切进去的）
    apply_action(conn, "start_stage", {"goal_id": gid, "stage": "UI"}, ZHOU, NOW)
    with pytest.raises(ActionError) as e:
        apply_action(conn, "start_stage", {"goal_id": gid, "stage": "UI"}, ZHOU, NOW)
    assert e.value.status == 409
    apply_action(conn, "end_stage", {"goal_id": gid, "stage": "产品"}, ZHOU, NOW)
    with pytest.raises(ActionError):
        apply_action(conn, "end_stage", {"goal_id": gid, "stage": "产品"}, ZHOU, NOW)
    assert [s.stage for s in fold(load_events(conn)).goals[gid].open_spans] == ["UI"]


def test_void_rules(conn):
    gid = _active_goal(conn)
    r = apply_action(conn, "start_stage", {"goal_id": gid, "stage": "UI"}, ZHOU, NOW)
    apply_action(conn, "end_stage", {"goal_id": gid, "stage": "UI"}, ZHOU, NOW)
    with pytest.raises(ActionError) as e:         # 苏禾不是原记录人也不是林夏
        apply_action(conn, "void", {"event_id": r.event_ids[0], "reason": "x"}, SU, NOW)
    assert e.value.status == 403
    before = len(load_events(conn))
    with pytest.raises(ActionError) as e:         # 作废「开始」后，后面的「结束」对不上 → 整条撤销
        apply_action(conn, "void", {"event_id": r.event_ids[0], "reason": "录错"}, ZHOU, NOW)
    assert e.value.status == 409 and len(load_events(conn)) == before
    lone = apply_action(conn, "create", {"title": "误录", "line": "客户端", "owner": "suhe"}, LIN, NOW)
    apply_action(conn, "void", {"event_id": lone.event_ids[0], "reason": "误录"}, LIN, NOW)   # 刚建好：整个撤掉
    assert lone.goal_id not in fold(load_events(conn)).goals
    with pytest.raises(ActionError) as e:         # 有后续记录的目标不能靠作废提议删掉
        first = [x for x in load_events(conn) if x.subject == f"goal:{gid}"][0]
        apply_action(conn, "void", {"event_id": first.id, "reason": "x"}, LIN, NOW)
    assert e.value.status == 409


def test_edit_goal_notes_and_late_baseline(conn):
    gid = _create(conn, line="客户端", owner="linxia")                       # 先不定计划完成日
    apply_action(conn, "edit_goal", {"goal_id": gid, "line": "管理与协作", "title": "团队看板"}, LIN, NOW)
    apply_action(conn, "change_due", {"goal_id": gid, "due": "2026-10-02", "reason": "定了"}, LIN, NOW)
    g = fold(load_events(conn)).goals[gid]
    assert (g.title, g.line, str(g.baseline_due)) == ("团队看板", "管理与协作", "2026-10-02")
    nid = apply_action(conn, "add_note", {"text": "看板今天进入 UI"}, LIN, NOW).event_ids[0]
    apply_action(conn, "resolve_note", {"note_id": nid, "summary": "开始 UI 环节"}, LIN, NOW)
    with pytest.raises(ActionError):
        apply_action(conn, "resolve_note", {"note_id": nid, "summary": "again"}, LIN, NOW)
    assert fold(load_events(conn)).notes[nid].summary == "开始 UI 环节"


def test_goals_nest_on_one_line_parent_first_no_cycles(conn):
    """目标可以一层层拆，但一棵树只在一条线上，上层要先立项。"""
    top = apply_action(conn, "create", {"title": "新协作模式落地", "line": "管理与协作", "owner": "linxia",
                                        "occurred_at": "2026-09-28T00:09:00-07:00"}, LIN, NOW).goal_id
    board = apply_action(conn, "create", {"title": "团队看板", "owner": "linxia", "parent_id": top,
                                          "due": "2026-10-02"}, LIN, NOW).goal_id
    leaf = apply_action(conn, "create", {"title": "上线部署", "owner": "zhouxing", "parent_id": board},
                        LIN, NOW).goal_id
    b = fold(load_events(conn))
    assert b.goals[leaf].line == "管理与协作" and b.goals[top].children == [board]
    cross = apply_action(conn, "create", {"title": "后台配置", "owner": "linxia", "parent_id": top, "line": "客户端"},
                         LIN, NOW).goal_id            # 子目标可以在别的线
    assert fold(load_events(conn)).goals[cross].line == "客户端"
    with pytest.raises(ActionError) as e:         # 下层不能比上层早立项
        apply_action(conn, "create", {"title": "x", "owner": "linxia", "parent_id": top,
                                      "occurred_at": "2026-09-27T10:00:00-07:00"}, LIN, NOW)
    assert e.value.status == 409
    early = apply_action(conn, "create", {"title": "旧事", "line": "客户端", "owner": "linxia",
                                          "occurred_at": "2026-09-01T10:00:00-07:00"}, LIN, NOW).goal_id
    with pytest.raises(ActionError) as e:         # 挂到更晚立项的目标下面也不行
        apply_action(conn, "edit_goal", {"goal_id": early, "parent_id": str(top)}, LIN, NOW)
    assert e.value.status == 409
    with pytest.raises(ActionError) as e:         # 不能把上层挂到自己的下层下面
        apply_action(conn, "edit_goal", {"goal_id": top, "parent_id": str(leaf)}, LIN, NOW)
    assert e.value.status == 409
    apply_action(conn, "edit_goal", {"goal_id": top, "line": "增长"}, LIN, NOW)
    b = fold(load_events(conn))                   # 换线：同线的下层跟着走，跨线的那块留在原地
    assert b.goals[leaf].line == "增长" and b.goals[cross].line == "客户端"
    with pytest.raises(ActionError) as e:         # 已经在这条线
        apply_action(conn, "edit_goal", {"goal_id": leaf, "line": "增长"}, LIN, NOW)
    assert e.value.status == 409
    with pytest.raises(ActionError) as e:         # 有子目标的不能靠作废撤掉
        first = [x for x in load_events(conn) if x.subject == f"goal:{top}"][0]
        apply_action(conn, "void", {"event_id": first.id, "reason": "x"}, LIN, NOW)
    assert e.value.status == 409
    nid = apply_action(conn, "add_note", {"text": "上线部署今天开始", "goal_id": leaf}, LIN, NOW).event_ids[0]
    assert fold(load_events(conn)).notes[nid].goal_id == leaf


def test_owner_splits_under_own_goal_only_to_self(conn):
    """负责人可以在自己负责的目标下面拆子目标给自己；
    拆给别人、挂到别人的目标下、另开一棵顶层目标，仍只有林夏能做。"""
    mine = _create(conn, title="产品崩溃率", line="客户端", owner="zhouxing")
    his = _create(conn, title="看板", line="管理与协作", owner="linxia")
    sub = apply_action(conn, "create", {"title": "修 3.8 的闪退", "owner": "zhouxing", "parent_id": mine},
                       ZHOU, NOW).goal_id
    b = fold(load_events(conn))
    assert b.goals[sub].parent_id == mine and b.goals[sub].owner == "zhouxing" and b.goals[sub].line == "客户端"
    for params in ({"title": "x", "owner": "suhe", "parent_id": mine},     # 拆给别人
                   {"title": "x", "owner": "zhouxing", "parent_id": his},      # 挂到别人的目标下
                   {"title": "x", "owner": "zhouxing", "line": "客户端"}):      # 另开一棵
        with pytest.raises(ActionError) as e:
            apply_action(conn, "create", params, ZHOU, NOW)
        assert e.value.status == 403
    assert len(fold(load_events(conn)).goals) == 3


def test_long_term_goal_has_no_due(conn):
    """长期负责的事（例：周行盯崩溃率）没有完成日，显示「长期」；具体动作拆成带日期的子目标。"""
    with pytest.raises(ActionError) as e:
        apply_action(conn, "create", {"title": "崩溃率", "line": "客户端", "owner": "zhouxing",
                                      "long_term": "1", "due": "2026-12-31"}, LIN, NOW)
    assert e.value.status == 400
    gid = _create(conn, title="产品崩溃率", line="客户端", owner="zhouxing", long_term="1")
    g = fold(load_events(conn)).goals[gid]
    assert g.long_term and g.latest_due is None
    with pytest.raises(ActionError) as e:
        apply_action(conn, "change_due", {"goal_id": gid, "due": "2026-12-31", "reason": "x"}, ZHOU, NOW)
    assert e.value.status == 409
    apply_action(conn, "edit_goal", {"goal_id": gid, "long_term": "0"}, ZHOU, NOW)
    assert not fold(load_events(conn)).goals[gid].long_term
    apply_action(conn, "change_due", {"goal_id": gid, "due": "2026-12-31", "reason": "改成有期限"}, ZHOU, NOW)
    with pytest.raises(ActionError) as e:                 # 定了日期就不能再标长期
        apply_action(conn, "edit_goal", {"goal_id": gid, "long_term": "1"}, ZHOU, NOW)
    assert e.value.status == 409


def test_backfill_allowed_again_after_voiding_a_wrong_record(conn):
    """实测：把记错时间的「开始业务」作废后，再按正确时间补录被自己的作废记录挡住。
    作废记录和被作废的记录都不该算「最后一条记录」。"""
    gid = apply_action(conn, "create", {"title": "母题", "line": "管理与协作", "owner": "linxia",
                                        "occurred_at": "2026-09-28T00:09:00-07:00"}, LIN, NOW).goal_id
    wrong = apply_action(conn, "start_stage", {"goal_id": gid, "stage": "业务",
                                               "occurred_at": "2026-09-29T09:18:00-07:00"}, LIN, NOW).event_ids[0]
    apply_action(conn, "void", {"event_id": wrong, "reason": "起点记错"}, LIN, NOW)
    apply_action(conn, "start_stage", {"goal_id": gid, "stage": "业务",
                                       "occurred_at": "2026-09-28T00:09:00-07:00"}, LIN, NOW)
    g = fold(load_events(conn)).goals[gid]
    assert [s.start.isoformat() for s in g.spans] == ["2026-09-28T07:09:00+00:00"]


def test_helper_records_only_own_stage_on_others_goal(conn):
    """替别人做环节的人能记自己那一段的起止，别的段仍归负责人或林夏。"""
    gid = _active_goal(conn)                      # 周行的目标，产品在进行（执行人周行）
    apply_action(conn, "start_stage", {"goal_id": gid, "stage": "测试"}, SU, NOW)   # 不填 executor = 她自己
    g = fold(load_events(conn)).goals[gid]
    assert g.running("测试").executor == "suhe"
    with pytest.raises(ActionError) as e:         # 替周行记他自己做的开发：不行
        apply_action(conn, "start_stage", {"goal_id": gid, "stage": "开发", "executor": "zhouxing"}, SU, NOW)
    assert e.value.status == 403
    with pytest.raises(ActionError) as e:         # 结束周行做的产品：不行
        apply_action(conn, "end_stage", {"goal_id": gid, "stage": "产品"}, SU, NOW)
    assert e.value.status == 403
    apply_action(conn, "end_stage", {"goal_id": gid, "stage": "测试"}, SU, NOW)     # 自己的段：行
    assert [s.stage for s in fold(load_events(conn)).goals[gid].open_spans] == ["产品"]
    apply_action(conn, "end_stage", {"goal_id": gid, "stage": "产品"}, ZHOU, NOW)   # 负责人照旧


def test_parent_cannot_complete_before_its_children(conn):
    """上层靠下层做成，补录也不能记成比下层先完成。"""
    parent = _create(conn, title="母题", owner="linxia")
    child = apply_action(conn, "create", {"title": "子块", "parent_id": parent, "owner": "zhouxing"}, LIN, NOW).goal_id
    with pytest.raises(ActionError) as e:         # 子目标还在进行
        apply_action(conn, "complete", {"goal_id": parent}, LIN, NOW)
    assert e.value.status == 409
    later = NOW + timedelta(days=2)
    apply_action(conn, "complete", {"goal_id": child}, ZHOU, later, )
    with pytest.raises(ActionError) as e:         # 补录成比子目标结束还早
        apply_action(conn, "complete", {"goal_id": parent, "occurred_at": (NOW + timedelta(days=1)).isoformat()}, LIN, later)
    assert e.value.status == 409 and "不能比下层先完成" in e.value.message
    apply_action(conn, "complete", {"goal_id": parent}, LIN, later + timedelta(hours=1))
    assert fold(load_events(conn)).goals[parent].status == "done"


def test_review_fixes_void_reference_seq_parent_rules(conn):
    """这几条规则：被依赖的目标不能撤（撤了整站 500）；作废挪动后编号不重复；
    改上层 / 换线只林夏；原地重挂不发新号；示例和真实不能互相依赖；事后改派不算「一起写的」。"""
    a = _create(conn, title="A", owner="linxia")
    b_ = apply_action(conn, "create", {"title": "B", "line": "客户端", "owner": "zhouxing"}, LIN, NOW)
    apply_action(conn, "declare_dependency", {"goal_id": a, "on_goal": b_.goal_id, "at_stage": "开发"}, LIN, NOW)
    with pytest.raises(ActionError) as e:                     # A 还依赖 B，不能撤 B
        apply_action(conn, "void", {"event_id": b_.event_ids[0], "reason": "x"}, LIN, NOW)
    assert e.value.status == 409 and "依赖" in e.value.message
    # 周行改不了上层和线；林夏原地重挂被拒
    x = apply_action(conn, "create", {"title": "X", "parent_id": a, "owner": "zhouxing"}, LIN, NOW).goal_id
    for params in ({"parent_id": "-"}, {"parent_id": b_.goal_id}, {"line": "客户端"}):
        with pytest.raises(ActionError) as e:
            apply_action(conn, "edit_goal", {"goal_id": x, **params}, ZHOU, NOW)
        assert e.value.status == 403
    with pytest.raises(ActionError) as e:
        apply_action(conn, "edit_goal", {"goal_id": x, "parent_id": a}, LIN, NOW)
    assert e.value.status == 409 and fold(load_events(conn)).goals[x].gnum == "G1.1"
    # Y 挪到 B 下再作废这次挪动，X、Y 编号不重复
    y = apply_action(conn, "create", {"title": "Y", "parent_id": a, "owner": "zhouxing"}, LIN, NOW).goal_id
    moved = apply_action(conn, "edit_goal", {"goal_id": y, "parent_id": b_.goal_id}, LIN, NOW)
    assert fold(load_events(conn)).goals[y].gnum == "G2.1"
    apply_action(conn, "void", {"event_id": moved.event_ids[0], "reason": "挪错了"}, LIN, NOW)
    goals = fold(load_events(conn)).goals
    assert goals[y].gnum == "G1.2" and goals[x].gnum == "G1.1" and goals[y].parent_id == a
    # 示例和真实不能互相依赖 / 互等
    s = apply_action(conn, "create", {"title": "S", "line": "客户端", "owner": "linxia", "sample": "1"}, LIN, NOW).goal_id
    with pytest.raises(ActionError) as e:
        apply_action(conn, "declare_dependency", {"goal_id": a, "on_goal": s, "at_stage": "开发"}, LIN, NOW)
    assert e.value.status == 409
    with pytest.raises(ActionError) as e:
        apply_action(conn, "pause", {"goal_id": a, "kind": "dependency", "depends_on": s}, LIN, NOW)
    assert e.value.status == 409
    # 周行自拆给自己，林夏事后改派苏禾，周行就不能再撤掉整个目标
    own = apply_action(conn, "create", {"title": "周行自拆", "parent_id": b_.goal_id, "owner": "zhouxing"}, ZHOU, NOW)
    apply_action(conn, "assign", {"goal_id": own.goal_id, "owner": "suhe"}, LIN, NOW + timedelta(minutes=1))
    with pytest.raises(ActionError) as e:
        apply_action(conn, "void", {"event_id": own.event_ids[0], "reason": "x"}, ZHOU, NOW + timedelta(minutes=2))
    assert e.value.status == 409


def test_source_number_recorded_unique_and_only_team_owner_backfills(conn):
    """来源号（出生号）：个人看板推上来的目标记下 L16 这类号，全看板唯一、一辈子不变。"""
    top = _create(conn, title="新协作模式落地", owner="linxia")
    gid = apply_action(conn, "create", {"title": "AI 记账", "owner": "linxia", "parent_id": top, "source": "l16"},
                       LIN, NOW).goal_id
    assert fold(load_events(conn)).goals[gid].source == "L16"          # 小写也认，存成大写
    for bad in ("G16", "L0", "L16.1", "X3", "16"):                      # 格式不对
        with pytest.raises(ActionError) as e:
            apply_action(conn, "create", {"title": "x", "line": "增长", "owner": "linxia", "source": bad}, LIN, NOW)
        assert e.value.status == 400
    with pytest.raises(ActionError) as e:                               # 重复
        apply_action(conn, "create", {"title": "x", "line": "增长", "owner": "linxia", "source": "L16"}, LIN, NOW)
    assert e.value.status == 409 and "L16" in e.value.message
    with pytest.raises(ActionError) as e:                               # 字母要和推的人对得上
        apply_action(conn, "create", {"title": "x", "line": "增长", "owner": "linxia", "source": "Z5"}, LIN, NOW)
    assert e.value.status == 400 and "周行" in e.value.message
    wang_top = _create(conn, title="推送服务", owner="zhouxing")
    z5 = apply_action(conn, "create", {"title": "周行拆的", "owner": "zhouxing", "parent_id": wang_top, "source": "Z5"},
                      ZHOU, NOW).goal_id
    assert fold(load_events(conn)).goals[z5].source == "Z5"
    old = _create(conn, title="早先推上来的", owner="zhouxing")
    with pytest.raises(ActionError) as e:                               # 负责人也不能补来源号，只林夏
        apply_action(conn, "edit_goal", {"goal_id": old, "source": "Z6"}, ZHOU, NOW)
    assert e.value.status == 403
    with pytest.raises(ActionError) as e:                               # 补的号也不能撞
        apply_action(conn, "edit_goal", {"goal_id": old, "source": "L16"}, LIN, NOW)
    assert e.value.status == 409
    apply_action(conn, "edit_goal", {"goal_id": old, "source": "Z6"}, LIN, NOW)
    with pytest.raises(ActionError) as e:                               # 定了不改
        apply_action(conn, "edit_goal", {"goal_id": old, "source": "Z7"}, LIN, NOW)
    assert e.value.status == 409 and "一辈子不变" in e.value.message
    specs = actions.action_specs()
    assert "source" in specs["create"]["optional"] and "source" in specs["edit_goal"]["optional"]


def test_wrong_source_backfill_is_fixed_by_voiding(conn, monkeypatch):
    """补错的来源号靠作废那条记录改（留痕）；看板折叠时再兜一次「来源号不能重复」。"""
    _create(conn, title="甲", owner="linxia", source="L1")
    b = _create(conn, title="乙", owner="linxia")
    fix = apply_action(conn, "edit_goal", {"goal_id": b, "source": "L2"}, LIN, NOW).event_ids[0]
    apply_action(conn, "void", {"event_id": fix, "reason": "补错了"}, LIN, NOW)
    assert fold(load_events(conn)).goals[b].source == ""                # 作废后回到没有来源号，可以重新补
    apply_action(conn, "edit_goal", {"goal_id": b, "source": "L3"}, LIN, NOW)
    assert fold(load_events(conn)).goals[b].source == "L3"
    monkeypatch.setattr(actions, "_source", lambda _b, raw: str(raw))    # 写入口漏查时，提交前的重算拦下、整条撤销
    with pytest.raises(ActionError) as e:
        apply_action(conn, "create", {"title": "丙", "line": "增长", "owner": "linxia", "source": "L3"}, LIN, NOW)
    assert e.value.status == 409 and "L3" in e.value.message
    assert len(fold(load_events(conn)).goals) == 2


def test_resolve_any_number_to_the_same_goal_even_after_moving(conn):
    """来源号、永久号（不带点的 G 号）、层级号三种都对到同一个目标；改挂后层级号变了，来源号和永久号照样能找到。"""
    from team_board.board.state import resolve
    top = _create(conn, title="新协作模式落地", owner="linxia")
    other = _create(conn, title="订阅系统", line="增长", owner="linxia")
    gid = apply_action(conn, "create", {"title": "AI 记账", "owner": "linxia", "parent_id": top, "source": "L16"},
                       LIN, NOW).goal_id
    b = fold(load_events(conn))
    g = b.goals[gid]
    assert g.gnum == f"G{top}.1" and g.permanent == f"G{gid}"
    for num in ("L16", "l16", f"G{gid}", f"G{top}.1", f" g{top}.1 "):
        assert resolve(b, num) is g, num
    apply_action(conn, "edit_goal", {"goal_id": gid, "parent_id": str(other)}, LIN, NOW)
    b = fold(load_events(conn))
    moved = b.goals[gid]
    assert moved.gnum == f"G{other}.1"
    assert resolve(b, "L16") is moved and resolve(b, f"G{gid}") is moved and resolve(b, f"G{other}.1") is moved
    assert resolve(b, f"G{top}.1") is None                             # 旧层级号不再认（只按现在的层级）
    for num in ("", "L99", "G999", "G1.9", "#174", "L"):
        assert resolve(b, num) is None, num


def test_done_what_backfilled_before_completion_is_rejected(conn):
    """「做了什么」补在完成之前，重放时被「完成」盖掉，接口却报成功。按那一刻的状态拒绝。"""
    gid = _active_goal(conn)
    apply_action(conn, "complete", {"goal_id": gid, "done_what": "原来的", "occurred_at": _la("08:55:00")}, LIN,
                 datetime(2026, 10, 2, 16, 0, tzinfo=timezone.utc))
    later = datetime(2026, 10, 2, 17, 0, tzinfo=timezone.utc)
    with pytest.raises(ActionError, match="还没完成"):
        apply_action(conn, "edit_goal", {"goal_id": gid, "done_what": "补在完成前", "occurred_at": _la("07:55:00")}, LIN, later)
    apply_action(conn, "edit_goal", {"goal_id": gid, "done_what": "补在完成后"}, LIN, later)
    assert fold(load_events(conn)).goals[gid].done_what == "补在完成后"
