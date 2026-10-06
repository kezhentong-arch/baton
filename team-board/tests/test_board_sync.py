from datetime import datetime, timezone

import pytest

from team_board.board import github_sync
from team_board.board.github_sync import (ISSUES_QUERY, PAGE_SIZE, TIMELINE_QUERY, backup_daily, busy_text,
                                          resolve_token, run_sync)
from team_board.board.issues import GhData, dwell, milestone_moves, subcontract_wait
from team_board.board.model import gh_due_day
from team_board.board.store import board_db_path, connect_board

NOW = datetime(2026, 10, 1, 18, 0, tzinfo=timezone.utc)
REPO = ("acme/app",)


def issue(number, labels=()):
    return {"number": number, "title": f"单{number}", "url": f"https://x/{number}", "state": "OPEN",
            "createdAt": "2026-09-01T00:00:00Z", "updatedAt": "2026-09-20T00:00:00Z",
            "closedAt": None, "body": "", "milestone": {"number": 9}, "parent": None,
            "labels": {"nodes": [{"name": x} for x in labels]}, "assignees": {"nodes": []}}


def lab(name, at, typ="LabeledEvent"):
    return {"__typename": typ, "createdAt": at, "label": {"name": name}}


def ms(title, at, typ="MilestonedEvent"):
    return {"__typename": typ, "createdAt": at, "milestoneTitle": title}


def page(nodes, has_next=False):
    return {"repository": {
        "milestones": {"nodes": [{"number": 9, "title": "v3.7", "state": "OPEN",
                                  "dueOn": "2026-07-22T00:00:00Z",
                                  "createdAt": "2026-08-20T00:00:00Z", "closedAt": None}]},
        "issues": {"pageInfo": {"hasNextPage": has_next, "endCursor": "p1"}, "nodes": nodes}}}


class FakeGitHub:
    """按查询种类分发：列表查询按顺序给页；单张查询按单号给事件（可分页、可抛错）。"""

    def __init__(self, pages, timelines, conn=None):
        self.pages, self.timelines, self.conn = list(pages), timelines, conn
        self.calls, self.in_tx = [], []

    def __call__(self, query, variables):
        self.calls.append((query, variables))
        if self.conn is not None:
            self.in_tx.append(self.conn.in_transaction)
        if query is ISSUES_QUERY:
            return self.pages.pop(0)
        assert query is TIMELINE_QUERY
        t = self.timelines[variables["number"]]
        if isinstance(t, Exception):
            raise t
        chunks = t if t and isinstance(t[0], list) else [t]      # [[第1页],[第2页]] 或单页
        i = 0 if variables["after"] is None else int(variables["after"])
        return {"repository": {"issue": {"timelineItems": {
            "totalCount": sum(len(c) for c in chunks),
            "pageInfo": {"hasNextPage": i + 1 < len(chunks), "endCursor": str(i + 1)},
            "nodes": chunks[i]}}}}


def test_list_pages_20_and_events_come_from_single_issue_queries(tmp_path):
    conn = connect_board(tmp_path)
    gh = FakeGitHub([page([issue(1, ["stage: todo"])], has_next=True), page([issue(2)])],
                    {1: [lab("stage: todo", "2026-09-02T00:00:00Z")], 2: []})
    res = run_sync(conn, gh, repos=REPO, now=NOW)
    assert res.ok and res.issues_seen == 2 and res.warnings == []
    lists = [v for q, v in gh.calls if q is ISSUES_QUERY]
    assert lists[0]["first"] == PAGE_SIZE == 20 and lists[1]["after"] == "p1"
    assert "timelineItems" not in ISSUES_QUERY          # 列表接口给的事件不可信，不再从那里取
    assert sorted(v["number"] for q, v in gh.calls if q is TIMELINE_QUERY) == [1, 2]
    assert [e.ref for e in GhData(conn).events[("acme/app", 1)]] == ["stage: todo"]


def test_timeline_pages_are_followed(tmp_path):
    conn = connect_board(tmp_path)
    gh = FakeGitHub([page([issue(1, ["stage: dev"])])], {1: [
        [lab("stage: todo", "2026-09-02T00:00:00Z")],
        [lab("stage: todo", "2026-09-03T00:00:00Z", "UnlabeledEvent"),
         lab("stage: dev", "2026-09-03T00:00:00Z")]]})
    run_sync(conn, gh, repos=REPO, now=NOW)
    evs = GhData(conn).events[("acme/app", 1)]
    assert [s for s, _a, _c in dwell(evs, NOW)] == ["To do", "Dev"]


def test_missing_events_stay_flagged_and_are_retried_until_complete(tmp_path):
    conn = connect_board(tmp_path)
    gh = FakeGitHub([page([issue(1, ["stage: review"]), issue(2, ["stage: done"])])],
                    {1: [], 2: RuntimeError("GitHub 返回 HTTP 502")})
    res = run_sync(conn, gh, repos=REPO, now=NOW)
    assert res.ok and res.issues_seen == 2         # 单张出错不让整轮失败
    assert res.warnings == ["acme/app#1：有标签但取不到状态记录",
                            "acme/app#2：抓取失败：GitHub 返回 HTTP 502"]
    # 下一轮：这两张单都没再更新（不在列表里），仍会被单独重抓并补齐
    gh = FakeGitHub([page([])], {1: [lab("stage: review", "2026-09-03T00:00:00Z")],
                                 2: [lab("stage: done", "2026-09-04T00:00:00Z")]})
    res = run_sync(conn, gh, repos=REPO, now=NOW)
    assert res.ok and res.warnings == []
    assert len(GhData(conn).events[("acme/app", 2)]) == 1


def test_failure_of_list_query_is_recorded_not_raised(tmp_path):
    conn = connect_board(tmp_path)

    def boom(q, v):
        raise RuntimeError("GitHub 返回 HTTP 502")

    res = run_sync(conn, boom, repos=REPO, now=NOW)
    assert not res.ok and "502" in res.error
    assert conn.execute("SELECT ok FROM gh_sync_runs").fetchone()["ok"] == 0


def test_milestone_due_keeps_github_date_and_moves(tmp_path):
    conn = connect_board(tmp_path)
    moved = [ms("v3.7", "2026-09-24T00:00:00Z", "DemilestonedEvent"), ms("v3.8", "2026-09-24T00:00:00Z")]
    gh = FakeGitHub([page([issue(5), issue(6)])], {
        5: [ms("v3.7", "2026-09-01T00:00:00Z")] + moved,
        # 同一秒里 GitHub 先给「挂上 v3.8」再给「摘下 v3.7」：仍然只算一次挪动，不多出「摘掉」
        6: [ms("v3.7", "2026-09-01T00:00:00Z"), moved[1], moved[0]]})
    run_sync(conn, gh, repos=REPO, now=NOW)
    gh_data = GhData(conn)
    assert str(gh_due_day(gh_data.milestones[("acme/app", 9)].due_on)) == "2026-07-22"
    assert sorted((m.number, m.src, m.dst) for m in milestone_moves(gh_data, "acme/app")) == [
        (5, "v3.7", "v3.8"), (6, "v3.7", "v3.8")]
    wait, delivered = subcontract_wait(gh_data.issues[("acme/app", 5)], [], NOW)
    assert delivered is False and round(wait.total_seconds() / 86400, 1) == 30.8


def test_sync_is_exclusive_and_network_runs_outside_transaction(tmp_path):
    conn = connect_board(tmp_path)
    gh = FakeGitHub([page([issue(1, ["stage: done"])])], {1: [lab("stage: done", "2026-09-03T00:00:00Z")]},
                    conn=conn)
    assert run_sync(conn, gh, repos=REPO, now=NOW).ok
    assert gh.in_tx and not any(gh.in_tx)          # 联网时不占着写事务
    with github_sync._SYNC_LOCK:
        busy = run_sync(conn, gh, repos=REPO, now=NOW)
    assert not busy.ok and busy.error == busy_text()


def test_github_sync_is_optional_off_by_default_and_fully_config_driven(tmp_path):
    """GitHub 同步默认关；仓库、标签映射、凭证的环境变量名都来自配置，凭证本身不进配置文件。"""
    from team_board import config
    from team_board.board.actions import ActionError, Who, action_specs, apply_action
    from team_board.board.issues import status_state
    from tests.conftest import make_cfg
    starter = config.parse_config(config.starter_config("en", data_dir=str(tmp_path / "d")))
    assert starter.github.enabled is False and starter.repos == ()
    assert resolve_token({"TEAM_BOARD_GITHUB_TOKEN": " t0 "}, starter) == "t0" and resolve_token({}, starter) is None
    custom = make_cfg(tmp_path, github={"enabled": True, "repos": ["acme/app"], "token_env": "MY_GH", "label_prefix": "s/",
                                        "label_map": [{"pattern": "s/doing", "state": "Doing"}], "delivered": ["Doing"]})
    assert resolve_token({"MY_GH": "x", "TEAM_BOARD_GITHUB_TOKEN": "y"}, custom) == "x"
    config.use(custom)
    assert status_state("s/doing") == "Doing" and status_state("bug") is None
    assert status_state("s/else") == "未登记标签：s/else"          # 前缀对得上、映射里没有：不猜，原样显示
    # 关着的时候：版本、关联单这几个操作不在操作说明里，调用也被明确拒绝；看板其余功能照常
    config.use(make_cfg(tmp_path, github={"enabled": False}))
    assert "link_issue" not in action_specs() and "track_version" not in action_specs() and "create" in action_specs()
    conn = connect_board(tmp_path / "off")
    who = Who("linxia", "web")
    gid = apply_action(conn, "create", {"title": "没有 GitHub 也能用", "line": "增长", "owner": "linxia"}, who, NOW).goal_id
    apply_action(conn, "start_stage", {"goal_id": gid, "stage": "开发"}, who, NOW)
    for action, params in (("track_version", {"ref": "acme/app#1"}),
                           ("link_issue", {"goal_id": gid, "repo": "acme/app", "number": 1, "kind": "link"})):
        with pytest.raises(ActionError) as e:
            apply_action(conn, action, params, who, NOW)
        assert e.value.status == 400 and "GitHub" in e.value.message
    with pytest.raises(config.ConfigError):                       # 开了却没写仓库：启动即拒
        make_cfg(tmp_path, github={"enabled": True, "repos": []})


def test_backup_once_per_local_day_and_keeps_latest(tmp_path):
    conn = connect_board(tmp_path)
    first = backup_daily(conn, tmp_path, now=NOW)
    assert first is not None and first.exists()
    assert backup_daily(conn, tmp_path, now=NOW) is None      # 同一天不再备份
    for d in range(2, 20):
        backup_daily(conn, tmp_path, now=datetime(2026, 10, d, 18, 0, tzinfo=timezone.utc), keep=14)
    assert len(list((board_db_path(tmp_path).parent / "backups").glob("*.sqlite"))) == 14


def test_manual_sync_runs_in_background_and_refuses_overlap(tmp_path):
    started = github_sync.start_background_sync(tmp_path, FakeGitHub([page([])], {}))
    assert started is True
    with github_sync._SYNC_LOCK:                 # 有一轮在跑时，不再开第二轮
        assert github_sync.start_background_sync(tmp_path, FakeGitHub([page([])], {})) is False
