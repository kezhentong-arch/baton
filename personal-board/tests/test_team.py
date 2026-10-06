from datetime import datetime, timezone
from unittest import mock

import app.team as team
from app.store import get_meta, open_db

NOW = datetime(2026, 10, 2, 16, 0, tzinfo=timezone.utc)
PAYLOAD = {"goals": [
    {"id": 2, "gnum": "G2", "title": "新协作方式落地", "line": "团队协作", "status": "进行中", "owner": "林夏", "parent_id": None, "sample": False, "long_term": False, "baseline_due": "", "latest_due": ""},
    {"id": 5, "gnum": "G2.2", "title": "个人看板", "line": "团队协作", "status": "进行中", "owner": "林夏", "parent_id": 2, "sample": False, "long_term": False, "baseline_due": "2026-10-02", "latest_due": ""},
    {"id": 7, "gnum": "G2.1.2", "title": "上线部署", "line": "团队协作", "status": "已完成", "owner": "周行", "parent_id": 3, "sample": False, "long_term": False, "baseline_due": "", "latest_due": ""},
    {"id": 99, "gnum": "G99", "title": "示例", "line": "产品", "status": "进行中", "owner": "林夏", "parent_id": None, "sample": True, "long_term": False, "baseline_due": "", "latest_due": ""},
]}


def test_pull_keeps_only_mine_and_parents(tmp_path):
    conn = open_db(tmp_path / "t.sqlite")
    with mock.patch.object(team, "fetch_state", return_value=PAYLOAD):
        r = team.pull(conn, NOW)
    assert r == {"ok": True, "pulled": 2, "error": ""}
    rows = {g["gnum"]: g for g in conn.execute("SELECT * FROM goals")}
    assert set(rows) == {"G2", "G2.2"} and rows["G2.2"]["parent_gnum"] == "G2" and rows["G2.2"]["due"] == "2026-10-02"
    assert rows["G2.2"]["source"] == "team"
    # pull again: rows are updated, not duplicated
    with mock.patch.object(team, "fetch_state", return_value=PAYLOAD):
        team.pull(conn, NOW)
    assert conn.execute("SELECT COUNT(*) FROM goals").fetchone()[0] == 2


def test_pull_failure_is_recorded_not_hidden(tmp_path):
    conn = open_db(tmp_path / "t.sqlite")
    with mock.patch.object(team, "fetch_state", side_effect=RuntimeError("连不上团队看板")):
        r = team.pull(conn, NOW)
    assert r["ok"] is False and "连不上" in r["error"]
    assert get_meta(conn, "team_pull_error") == "连不上团队看板"
    assert conn.execute("SELECT COUNT(*) FROM goals").fetchone()[0] == 0


def test_pull_claims_locally_created_goal_after_rename(tmp_path):
    """The guide's flow: create here (birth number) → push → goal_update to the G number → the next pull must not hit the unique key."""
    from app.actions import apply_action
    conn = open_db(tmp_path / "t.sqlite")
    conn.execute("INSERT INTO meta(key, value) VALUES('person','linxia')")
    r = apply_action(conn, "goal_create", {"title": "新块", "line": "团队协作"}, NOW)
    apply_action(conn, "goal_update", {"goal": r.gnum, "gnum": "G2.5"}, NOW)
    payload = {"goals": PAYLOAD["goals"] + [{"id": 9, "gnum": "G2.5", "title": "新块", "line": "团队协作", "status": "进行中", "owner": "林夏",
                                            "parent_id": 2, "sample": False, "long_term": False, "baseline_due": "", "latest_due": ""}]}
    with mock.patch.object(team, "fetch_state", return_value=payload):
        res = team.pull(conn, NOW)
    assert res["ok"] is True
    row = conn.execute("SELECT team_id, source FROM goals WHERE gnum='G2.5'").fetchone()
    assert row["team_id"] == 9 and row["source"] == "team"
    assert conn.execute("SELECT COUNT(*) FROM goals WHERE gnum='G2.5'").fetchone()[0] == 1


def test_pull_does_not_clobber_local_pending_and_closes_stages_when_team_done(tmp_path):
    from app.actions import apply_action, open_stages
    from datetime import timedelta
    conn = open_db(tmp_path / "t.sqlite")
    conn.execute("INSERT INTO meta(key, value) VALUES('person','linxia')")
    with mock.patch.object(team, "fetch_state", return_value=PAYLOAD):
        team.pull(conn, NOW)
    # completed locally but not pushed yet: the team board saying "in progress" must not overwrite it
    apply_action(conn, "complete", {"goal": "G2.2"}, NOW + timedelta(minutes=1))
    with mock.patch.object(team, "fetch_state", return_value=PAYLOAD):
        team.pull(conn, NOW + timedelta(minutes=2))
    g = conn.execute("SELECT status, done_at FROM goals WHERE gnum='G2.2'").fetchone()
    assert g["status"] == "done" and g["done_at"]
    # done on the team board while a stage is still open here: the pull ends the stage and marks the goal done
    apply_action(conn, "stage_start", {"goal": "G2", "stage": "业务", "_sync": "pushed"}, NOW, internal=True)  # a stage already pushed
    done_payload = {"goals": [dict(x, status="已完成") if x["gnum"] == "G2" else x for x in PAYLOAD["goals"]]}
    with mock.patch.object(team, "fetch_state", return_value=done_payload):
        team.pull(conn, NOW + timedelta(minutes=3))
    gid = conn.execute("SELECT id FROM goals WHERE gnum='G2'").fetchone()[0]
    assert open_stages(conn, gid) == {}
    assert conn.execute("SELECT status FROM goals WHERE gnum='G2'").fetchone()[0] == "done"


def test_pull_backfills_records_for_team_side_changes(tmp_path):
    """What happened on the team board must leave entries here when pulled: creation, completion, a changed plan, a pause."""
    from datetime import timedelta
    conn = open_db(tmp_path / "t.sqlite")
    conn.execute("INSERT INTO meta(key, value) VALUES('person','linxia')")
    with mock.patch.object(team, "fetch_state", return_value=PAYLOAD):
        team.pull(conn, NOW)
    kinds = lambda gnum: [r["kind"] for r in conn.execute(  # noqa: E731
        "SELECT e.kind FROM entries e JOIN goals g ON g.id=e.goal_id WHERE g.gnum=? AND e.voided_at IS NULL ORDER BY e.id", (gnum,))]
    assert kinds("G2.2") == ["goal_create"] and kinds("G2") == ["goal_create"]
    # a goal without a creation entry gets one on the next pull, and only one
    conn.execute("DELETE FROM entries")
    with mock.patch.object(team, "fetch_state", return_value=PAYLOAD):
        team.pull(conn, NOW + timedelta(minutes=1))
        team.pull(conn, NOW + timedelta(minutes=2))
    assert kinds("G2.2") == ["goal_create"]
    changed = {"goals": [dict(PAYLOAD["goals"][0], paused="等依赖"),
                         dict(PAYLOAD["goals"][1], status="已完成", latest_due="2026-10-05"), PAYLOAD["goals"][2], PAYLOAD["goals"][3]]}
    with mock.patch.object(team, "fetch_state", return_value=changed):
        team.pull(conn, NOW + timedelta(minutes=3))
    assert kinds("G2.2") == ["goal_create", "due", "complete"]
    assert kinds("G2") == ["goal_create", "note"]
    g22 = conn.execute("SELECT status, due FROM goals WHERE gnum='G2.2'").fetchone()
    assert g22["status"] == "done" and g22["due"] == "2026-10-05"
    with mock.patch.object(team, "fetch_state", return_value=changed):  # pull again: nothing changed, nothing logged
        team.pull(conn, NOW + timedelta(minutes=4))
    assert kinds("G2.2") == ["goal_create", "due", "complete"] and kinds("G2") == ["goal_create", "note"]


def test_pull_flags_goal_no_longer_mine(tmp_path):
    """A goal whose owner changed on the team board must not pretend to be in progress forever: it gets a blocker and one note, once."""
    from datetime import timedelta
    conn = open_db(tmp_path / "t.sqlite")
    conn.execute("INSERT INTO meta(key, value) VALUES('person','linxia')")
    with mock.patch.object(team, "fetch_state", return_value=PAYLOAD):
        team.pull(conn, NOW)
    moved = {"goals": [PAYLOAD["goals"][0], dict(PAYLOAD["goals"][1], owner="周行"), PAYLOAD["goals"][2], PAYLOAD["goals"][3]]}
    with mock.patch.object(team, "fetch_state", return_value=moved):
        team.pull(conn, NOW + timedelta(minutes=1))
        team.pull(conn, NOW + timedelta(minutes=2))
    row = conn.execute("SELECT blocker, status FROM goals WHERE gnum='G2.2'").fetchone()
    assert row["blocker"] == "团队看板：已不归我负责" and row["status"] == "active"
    notes = conn.execute("SELECT COUNT(*) FROM entries e JOIN goals g ON g.id=e.goal_id WHERE g.gnum='G2.2' AND e.kind='note'").fetchone()[0]
    assert notes == 1


def test_pull_keeps_local_hour_when_team_day_matches(tmp_path):
    """The team board's plan may be a bare date while the local one carries an hour ("Friday before 8"). Same day: the
    local hour is kept. A different day on the team board: the team board wins (and the hour goes)."""
    from app.actions import apply_action
    from datetime import timedelta
    conn = open_db(tmp_path / "t.sqlite")
    conn.execute("INSERT INTO meta(key, value) VALUES('person','linxia')")
    with mock.patch.object(team, "fetch_state", return_value=PAYLOAD):
        team.pull(conn, NOW)
    r = apply_action(conn, "goal_update", {"goal": "G2.2", "due": "2026-10-02 08:00"}, NOW + timedelta(minutes=1))
    apply_action(conn, "sync_mark", {"entry_ids": r.ids, "status": "skip"}, NOW + timedelta(minutes=2))  # the team board already says 10-02: nothing to push
    with mock.patch.object(team, "fetch_state", return_value=PAYLOAD):
        team.pull(conn, NOW + timedelta(minutes=3))
    assert conn.execute("SELECT due FROM goals WHERE gnum='G2.2'").fetchone()[0] == "2026-10-02 08:00"
    assert conn.execute("SELECT COUNT(*) FROM entries WHERE kind='due'").fetchone()[0] == 1  # no extra "changed on the team board" entry
    moved = {"goals": [dict(x, latest_due="2026-10-03") if x["gnum"] == "G2.2" else x for x in PAYLOAD["goals"]]}
    with mock.patch.object(team, "fetch_state", return_value=moved):
        team.pull(conn, NOW + timedelta(minutes=4))
    assert conn.execute("SELECT due FROM goals WHERE gnum='G2.2'").fetchone()[0] == "2026-10-03"
    assert conn.execute("SELECT COUNT(*) FROM entries WHERE kind='due'").fetchone()[0] == 2


def test_pull_uses_team_moments_and_fixes_earlier_guesses(tmp_path):
    """When the team board gives the real moments (creation, stage spans, completion, pauses) and the version, the
    pull logs them at those moments, and entries once guessed from the pull time are corrected."""
    from datetime import timedelta
    conn = open_db(tmp_path / "t.sqlite")
    conn.execute("INSERT INTO meta(key, value) VALUES('person','linxia')")
    with mock.patch.object(team, "fetch_state", return_value=PAYLOAD):   # no moments given: backfilled at pull time
        team.pull(conn, NOW)
    created = conn.execute("SELECT e.occurred_at FROM entries e JOIN goals g ON g.id=e.goal_id WHERE g.gnum='G2.2' AND e.kind='goal_create'").fetchone()[0]
    assert created == "2026-10-02T16:00:00+00:00"
    rich = {"goals": [
        dict(PAYLOAD["goals"][0], approved_at="2026-09-28T07:09:00+00:00", spans=[{"stage": "业务", "start": "2026-09-28T07:10:00+00:00", "end": ""}],
             current_stages=["业务"], pauses=[], version=None),
        dict(PAYLOAD["goals"][1], approved_at="2026-10-02T05:50:00+00:00", latest_due="2026-10-02 08:00", status="已完成", done_at="2026-10-02T12:36:53+00:00",
             spans=[{"stage": "开发", "start": "2026-10-02T08:10:00+00:00", "end": "2026-10-02T12:36:00+00:00"}],
             current_stages=[], pauses=[{"kind": "等依赖", "start": "2026-10-02T05:51:00+00:00", "end": "2026-10-02T12:43:00+00:00"}],
             version={"name": "看板 v1.0"}),
        PAYLOAD["goals"][2], PAYLOAD["goals"][3]]}
    with mock.patch.object(team, "fetch_state", return_value=rich):
        team.pull(conn, NOW + timedelta(minutes=5))
    rows = lambda gnum: conn.execute(  # noqa: E731
        "SELECT e.kind, e.stage, e.occurred_at, e.text FROM entries e JOIN goals g ON g.id=e.goal_id WHERE g.gnum=? AND e.voided_at IS NULL ORDER BY e.occurred_at, e.id", (gnum,)).fetchall()
    g22 = rows("G2.2")
    assert [(r["kind"], r["occurred_at"]) for r in g22] == [
        ("goal_create", "2026-10-02T05:50:00+00:00"),       # creation corrected; no longer the pull time
        ("complete", "2026-10-02T12:36:53+00:00"),
        ("due", "2026-10-02T16:05:00+00:00"),
    ]
    assert "按拉取时刻" not in g22[0]["text"] and "按拉取时刻" not in g22[1]["text"]
    goal = conn.execute("SELECT due, version_name, created_at, done_at FROM goals WHERE gnum='G2.2'").fetchone()
    assert goal["due"] == "2026-10-02 08:00" and goal["version_name"] == "看板 v1.0"
    assert goal["created_at"] == "2026-10-02T05:50:00+00:00" and goal["done_at"] == "2026-10-02T12:36:53+00:00"
    g2 = rows("G2")
    assert [(r["kind"], r["stage"], r["occurred_at"]) for r in g2] == [
        ("goal_create", None, "2026-09-28T07:09:00+00:00"),
        ("stage_start", "业务", "2026-09-28T07:10:00+00:00"),
    ]
    # first pulled when already done on the team board: creation and completion at the team board's moments
    done = {"goals": rich["goals"] + [{"id": 30, "gnum": "G2.9", "title": "早做完的", "line": "团队协作", "status": "已完成", "owner": "林夏", "parent_id": 2,
                                        "sample": False, "long_term": False, "baseline_due": "", "latest_due": "",
                                        "approved_at": "2026-09-29T01:00:00+00:00", "done_at": "2026-09-30T02:00:00+00:00", "spans": [], "pauses": []}]}
    with mock.patch.object(team, "fetch_state", return_value=done):
        team.pull(conn, NOW + timedelta(minutes=6))
    assert [(r["kind"], r["occurred_at"]) for r in rows("G2.9")] == [
        ("goal_create", "2026-09-29T01:00:00+00:00"), ("complete", "2026-09-30T02:00:00+00:00")]


def test_pull_takes_team_baseline_due(tmp_path):
    """Delay is measured from the first plan ever set, and the team board is the authority on it: taken on insert and on update, even with unpushed local changes."""
    conn = open_db(tmp_path / "t.sqlite")
    moved = {"goals": [dict(x, baseline_due="2026-10-02", latest_due="2026-10-02 08:00") if x["gnum"] == "G2.2" else x
                       for x in PAYLOAD["goals"]]}
    with mock.patch.object(team, "fetch_state", return_value=moved):
        team.pull(conn, NOW)
    row = conn.execute("SELECT due, baseline_due FROM goals WHERE gnum='G2.2'").fetchone()
    assert (row["due"], row["baseline_due"]) == ("2026-10-02 08:00", "2026-10-02")
    conn.execute("UPDATE goals SET baseline_due='2026-09-30' WHERE gnum='G2.2'")   # a wrong local baseline goes back to the team board's on the next pull
    with mock.patch.object(team, "fetch_state", return_value=moved):
        team.pull(conn, NOW)
    assert conn.execute("SELECT baseline_due FROM goals WHERE gnum='G2.2'").fetchone()[0] == "2026-10-02"
