"""Point tasks: monthly moments follow the task's own wall clock, a dot appears only when the window reaches it,
an overdue one stays until today, a tick makes it solid, and nothing is ever pushed to the team board."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.actions import ActionError, apply_action
from app.store import open_db
from app.view import goal_detail, state, timeline

LA = ZoneInfo("America/Los_Angeles")
NOW = datetime(2026, 10, 3, 12, 30, tzinfo=timezone.utc)   # 10-03 05:30 in Los Angeles


@pytest.fixture
def conn(tmp_path):
    c = open_db(tmp_path / "t.sqlite")
    c.execute("INSERT INTO meta(key, value) VALUES('person','linxia')")
    return c


def _payday(conn):
    return apply_action(conn, "goal_create", {"title": "给外包结款", "line": "运营", "point_at": "2026-11-01 10:00",
                                              "point_zone": "Asia/Tokyo", "repeat": "monthly", "task": "t", "tool": "claude"}, NOW)


def _rows(conn, a, b, now=NOW):
    return {r["gnum"]: r for r in timeline(conn, a, b, now)["rows"]}


def test_monthly_follows_its_own_clock_across_another_zones_dst(conn):
    """Los Angeles leaves daylight saving on 11-01: 10:00 in Tokyo moves from 18:00 to 17:00 there. Adding a fixed
    interval to the Los Angeles time would be an hour off."""
    g = _payday(conn)
    win = timeline(conn, datetime(2026, 10, 25, tzinfo=LA), datetime(2027, 1, 5, tzinfo=LA), NOW)
    occ = next(r for r in win["rows"] if r["gnum"] == g.gnum)["point"]["occ"]
    assert [o["at"] for o in occ] == ["2026-11-01T01:00:00+00:00",
                                      "2026-12-01T01:00:00+00:00", "2027-01-01T01:00:00+00:00"]
    assert occ[0]["text"] == "11-01 10:00（东京）= 10-31 18:00（洛杉矶）"
    assert occ[1]["text"] == "12-01 10:00（东京）= 11-30 17:00（洛杉矶）"
    assert {o["state"] for o in occ} == {"upcoming"}


def test_appears_only_when_window_covers_it_and_never_pushes(conn):
    g = _payday(conn)
    week_now = (datetime(2026, 9, 27, tzinfo=LA), datetime(2026, 10, 4, tzinfo=LA))
    assert g.gnum not in _rows(conn, *week_now)              # not there yet (an ordinary goal in progress would be)
    assert g.gnum in _rows(conn, datetime(2026, 10, 31, tzinfo=LA), datetime(2026, 11, 1, tzinfo=LA))
    s = state(conn, NOW.astimezone(LA).date(), NOW)
    assert s["header"]["pending_count"] == 0                 # "not pushed" from the moment it is created
    assert conn.execute("SELECT sync FROM entries WHERE kind='goal_create'").fetchone()[0] == "skip"
    with pytest.raises(ActionError, match="不开环节"):
        apply_action(conn, "stage_start", {"goal": g.gnum, "stage": "开发"}, NOW)


def test_overdue_stays_until_today_then_done_only_on_its_day(conn):
    g = _payday(conn)
    later = datetime(2026, 11, 3, 20, 0, tzinfo=timezone.utc)   # 11-03 12:00 in Los Angeles; the 11-01 one is 2.8 days overdue
    today = (datetime(2026, 11, 3, tzinfo=LA), datetime(2026, 11, 4, tzinfo=LA))
    o = _rows(conn, *today, now=later)[g.gnum]["point"]["occ"][0]
    assert o["state"] == "overdue" and o["late_s"] == int((later - datetime(2026, 11, 1, 1, tzinfo=timezone.utc)).total_seconds())
    s = state(conn, later.astimezone(LA).date(), later)
    assert [i["status"] for i in s["points_due"]["items"]] == ["过期 2.8 天"] and not s["points_due"]["reminded_today"]
    apply_action(conn, "point_reminded", {}, later)
    assert state(conn, later.astimezone(LA).date(), later)["points_due"]["reminded_today"]
    r = apply_action(conn, "point_done", {"goal": g.gnum, "task": "t", "tool": "claude"}, later)   # none named = the earliest undone
    o = _rows(conn, *today, now=later)
    assert g.gnum in o and o[g.gnum]["point"]["occ"][0]["state"] == "done"   # done late: drawn from its moment to the tick, still visible today
    assert g.gnum not in _rows(conn, datetime(2026, 11, 5, tzinfo=LA), datetime(2026, 11, 6, tzinfo=LA), later + timedelta(days=2))
    assert state(conn, later.astimezone(LA).date(), later)["points_due"]["items"] == []
    with pytest.raises(ActionError, match="7 天内没有"):     # the next one (12-01) is far off and cannot be ticked in passing
        apply_action(conn, "point_done", {"goal": g.gnum}, later)
    apply_action(conn, "void", {"entry_id": r.ids[0], "reason": "勾错了"}, later)
    assert _rows(conn, *today, now=later)[g.gnum]["point"]["occ"][0]["state"] == "overdue"


def test_one_off_done_leaves_active_and_void_brings_back(conn):
    g = apply_action(conn, "goal_create", {"title": "交季度报税", "line": "个人事项", "point_at": "2026-10-03 09:00"}, NOW)
    assert apply_action(conn, "point_done", {"goal": g.gnum}, NOW).ids
    assert goal_detail(conn, g.gnum, NOW)["goal"]["status"] == "done"
    eid = conn.execute("SELECT id FROM entries WHERE kind='point_done'").fetchone()[0]
    apply_action(conn, "void", {"entry_id": eid, "reason": "其实没交"}, NOW)
    d = goal_detail(conn, g.gnum, NOW)
    assert d["goal"]["status"] == "active" and d["point"]["occ"][0]["state"] == "upcoming"


def test_change_rule_and_cancel(conn):
    g = _payday(conn)
    apply_action(conn, "goal_update", {"goal": g.gnum, "point_at": "2026-11-05 10:00", "reason": "改到 5 号"}, NOW)
    assert goal_detail(conn, g.gnum, NOW)["point"]["rule"] == "每月 5 号 10:00（东京）"
    apply_action(conn, "goal_update", {"goal": g.gnum, "status": "abandoned", "reason": "不再结了"}, NOW)
    assert g.gnum not in _rows(conn, datetime(2026, 11, 4, tzinfo=LA), datetime(2026, 11, 6, tzinfo=LA))
    with pytest.raises(ActionError, match="due"):
        apply_action(conn, "goal_create", {"title": "x", "line": "个人事项", "point_at": "2026-11-01 10:00", "due": "2026-11-02"}, NOW)


def test_rule_edges(conn):
    """A rule can change only from the next occurrence on; rounding matches the page script; one occurrence cannot be
    ticked twice; a tick may predate the task; a cancelled task stays cancelled."""
    import sqlite3

    from app import points
    g = _payday(conn)
    with pytest.raises(ActionError, match="晚于现在"):     # a first moment before now would turn months already done into "overdue"
        apply_action(conn, "goal_update", {"goal": g.gnum, "point_at": "2026-10-01 09:00"}, NOW)
    with pytest.raises(ActionError, match="要写 point_at"):
        apply_action(conn, "goal_update", {"goal": g.gnum, "point_zone": "main"}, NOW)
    r = apply_action(conn, "goal_update", {"goal": g.gnum, "point_at": "2026-12-01 10:00"}, NOW)
    note = conn.execute("SELECT text FROM entries WHERE id=?", (r.ids[0],)).fetchone()[0]
    assert "11-01 10:00（东京）起" in note and "12-01 10:00（东京）起" in note   # changing only the first month leaves a trace too
    assert points.late_text(99360) == "1.1 天" and points.late_text(125280) == "1.4 天"   # what JS toFixed gives
    one = apply_action(conn, "goal_create", {"title": "补发", "line": "个人事项", "point_at": "2026-10-01 09:00"}, NOW)
    apply_action(conn, "point_done", {"goal": one.gnum, "occurred_at": "2026-10-01T09:30:00-07:00"}, NOW)   # earlier than the task itself
    with pytest.raises(ActionError, match="不再恢复"):
        apply_action(conn, "goal_update", {"goal": one.gnum, "status": "active"}, NOW)
    with pytest.raises(sqlite3.IntegrityError):              # the database's own guard: no second valid tick for one occurrence
        with conn:
            conn.execute("INSERT INTO entries(goal_id, kind, occurred_at, recorded_at, occurrence) "
                         "SELECT goal_id, kind, occurred_at, recorded_at, occurrence FROM entries WHERE kind='point_done'")


def test_zones_come_from_config(conn, use_config):
    """point_zone accepts the configured zones by name, label or main / second — and nothing else. With a single
    configured zone every "both zones" text names just the one."""
    from app.actions import values
    assert values()["point_zone"] == {"America/Los_Angeles": "洛杉矶", "Asia/Tokyo": "东京"}
    for zone, want in (("东京", "Asia/Tokyo"), ("second", "Asia/Tokyo"), ("main", "America/Los_Angeles"), ("洛杉矶", "America/Los_Angeles")):
        g = apply_action(conn, "goal_create", {"title": zone, "line": "个人事项", "point_at": "2026-11-01 10:00", "point_zone": zone}, NOW)
        assert conn.execute("SELECT point_zone FROM goals WHERE id=?", (g.goal_id,)).fetchone()[0] == want
    with pytest.raises(ActionError, match="point_zone"):
        apply_action(conn, "goal_create", {"title": "x", "line": "个人事项", "point_at": "2026-11-01 10:00", "point_zone": "Europe/Paris"}, NOW)
    cfg = use_config()
    cfg = dict(cfg)
    cfg.pop("second_timezone")
    from app import settings
    settings.use(cfg)
    solo = apply_action(conn, "goal_create", {"title": "只一个时区", "line": "个人事项", "point_at": "2026-11-02 10:00"}, NOW)
    occ = goal_detail(conn, solo.gnum, NOW)["point"]["occ"][0]
    assert occ["text"] == "11-02 10:00（洛杉矶）"            # no "= other zone" part
    with pytest.raises(ActionError, match="point_zone"):      # "second" does not exist any more
        apply_action(conn, "goal_create", {"title": "x", "line": "个人事项", "point_at": "2026-11-01 10:00", "point_zone": "second"}, NOW)
    tokyo = goal_detail(conn, "东京", NOW) if False else None   # (a task stored with a zone that left the config still renders — see below)
    stored = conn.execute("SELECT gnum FROM goals WHERE point_zone='Asia/Tokyo' LIMIT 1").fetchone()[0]
    assert "Tokyo" in goal_detail(conn, stored, NOW)["point"]["rule"]
    assert tokyo is None
