from datetime import datetime, timedelta, timezone

import pytest

from app.actions import apply_action
from app.store import open_db
from app.view import day_counts, state, timeline

T0 = datetime(2026, 9, 28, 16, 0, tzinfo=timezone.utc)


@pytest.fixture
def conn(tmp_path):
    c = open_db(tmp_path / "t.sqlite")
    c.execute("INSERT INTO meta(key, value) VALUES('person','linxia')")
    return c


def test_rows_follow_window_and_spans_cross_edges(conn):
    done = apply_action(conn, "goal_create", {"title": "早做完的", "line": "产品", "occurred_at": T0.isoformat()}, T0)
    apply_action(conn, "stage_start", {"goal": done.gnum, "stage": "开发", "occurred_at": T0.isoformat()}, T0)
    apply_action(conn, "complete", {"goal": done.gnum, "occurred_at": (T0 + timedelta(days=5)).isoformat()}, T0 + timedelta(days=5))
    live = apply_action(conn, "goal_create", {"title": "一直在的", "line": "增长", "occurred_at": T0.isoformat()}, T0)
    now = T0 + timedelta(days=10)
    # the window covers the middle of a finished goal: the row is there and its span crosses both edges
    win = timeline(conn, T0 + timedelta(days=2), T0 + timedelta(days=3), now)
    gnums = {r["gnum"] for r in win["rows"]}
    assert gnums == {done.gnum, live.gnum}
    span = next(r for r in win["rows"] if r["gnum"] == done.gnum)["spans"][0]
    assert span["start"] < win["start"] and span["end"] > win["end"]
    # the window lies after its completion: the finished one is gone, the one in progress stays
    later = timeline(conn, T0 + timedelta(days=7), T0 + timedelta(days=8), now)
    assert {r["gnum"] for r in later["rows"]} == {live.gnum}


def test_state_groups_day_entries_by_hour_and_counts_pending(conn):
    g = apply_action(conn, "goal_create", {"title": "x", "line": "团队协作", "occurred_at": T0.isoformat()}, T0)
    at = datetime(2026, 10, 2, 16, 12, tzinfo=timezone.utc)  # 10-02 09:12 in Los Angeles
    apply_action(conn, "log", {"goal": g.gnum, "text": "开工", "kind": "start", "task": "个人看板", "tool": "claude",
                               "occurred_at": at.isoformat()}, at)
    apply_action(conn, "stage_start", {"goal": g.gnum, "stage": "开发", "occurred_at": (at + timedelta(minutes=3)).isoformat()}, at)
    s = state(conn, at.astimezone(__import__("zoneinfo").ZoneInfo("America/Los_Angeles")).date(), at + timedelta(hours=1))
    assert [h["hour"] for h in s["hours"]] == ["09"]
    assert [e["kind"] for e in s["hours"][0]["entries"]] == ["start", "stage_start"]
    assert s["header"]["pending_count"] == 2  # creation + stage start (team line)
    assert next(ln for ln in s["lines"] if ln["name"] == "团队协作")["goals"][0]["open_stages"] == ["开发"]


def test_no_stage_done_goal_appears_by_created_to_done_span(conn):
    """A goal without stages is drawn as a grey "created → done" bar; a window in the middle of it must show the row, as timeline.js does."""
    g = apply_action(conn, "goal_create", {"title": "笼统的事", "line": "团队协作", "occurred_at": T0.isoformat()}, T0)
    apply_action(conn, "complete", {"goal": g.gnum, "occurred_at": (T0 + timedelta(days=20)).isoformat()}, T0 + timedelta(days=20))
    now = T0 + timedelta(days=40)
    mid = timeline(conn, T0 + timedelta(days=10), T0 + timedelta(days=11), now)
    assert g.gnum in {r["gnum"] for r in mid["rows"]}
    after = timeline(conn, T0 + timedelta(days=30), T0 + timedelta(days=31), now)
    assert g.gnum not in {r["gnum"] for r in after["rows"]}


def test_active_goal_absent_before_created_but_stays_after(conn):
    """A goal in progress is always there — except on days before it was created."""
    g = apply_action(conn, "goal_create", {"title": "后立的", "line": "团队协作", "occurred_at": (T0 + timedelta(days=5)).isoformat()}, T0 + timedelta(days=5))
    now = T0 + timedelta(days=6)
    before = timeline(conn, T0, T0 + timedelta(days=1), now)
    assert g.gnum not in {r["gnum"] for r in before["rows"]}
    future = timeline(conn, T0 + timedelta(days=30), T0 + timedelta(days=31), now)
    assert g.gnum in {r["gnum"] for r in future["rows"]}


def test_goal_update_rejects_done_and_abandon_closes_stages(conn):
    from app.actions import ActionError, open_stages
    g = apply_action(conn, "goal_create", {"title": "x", "line": "产品", "occurred_at": T0.isoformat()}, T0)
    apply_action(conn, "stage_start", {"goal": g.gnum, "stage": "开发"}, T0)
    with pytest.raises(ActionError, match="complete"):
        apply_action(conn, "goal_update", {"goal": g.gnum, "status": "done"}, T0)
    apply_action(conn, "goal_update", {"goal": g.gnum, "status": "abandoned", "reason": "不做了"}, T0 + timedelta(days=1))
    assert open_stages(conn, g.goal_id) == {}
    row = conn.execute("SELECT status, done_at FROM goals WHERE id=?", (g.goal_id,)).fetchone()
    assert row["status"] == "abandoned" and row["done_at"]
    assert conn.execute("SELECT COUNT(*) FROM entries WHERE goal_id=? AND kind='abandon' AND sync='pending'", (g.goal_id,)).fetchone()[0] == 1


def test_week_strip_centers_on_selected_day_and_day_counts(conn):
    """The 7-day strip is centred on the selected day and never runs past today; the calendar counts entries per day."""
    from datetime import date
    g = apply_action(conn, "goal_create", {"title": "x", "line": "产品", "occurred_at": T0.isoformat()}, T0)
    apply_action(conn, "log", {"goal": g.gnum, "text": "a", "occurred_at": (T0 + timedelta(days=1)).isoformat()}, T0 + timedelta(days=1))
    now = T0 + timedelta(days=10)  # 10-08 in Los Angeles
    past = state(conn, date(2026, 9, 30), now)["week"]
    assert [w["day"] for w in past] == [f"2026-09-{d}" for d in ("27", "28", "29", "30")] + ["2026-10-01", "2026-10-02", "2026-10-03"]
    today = state(conn, date(2026, 10, 8), now)["week"]
    assert today[-1]["day"] == "2026-10-08" and today[0]["day"] == "2026-10-02"  # today selected: the six days before it
    near = state(conn, date(2026, 10, 7), now)["week"]
    assert near[-1]["day"] == "2026-10-08"  # next to today: the strip stops at today
    dc = day_counts(conn, date(2026, 9, 28), date(2026, 9, 30))["counts"]
    assert dc == {"2026-09-28": 1, "2026-09-29": 1}
    with pytest.raises(ValueError):
        day_counts(conn, date(2026, 9, 30), date(2026, 9, 1))


def test_rows_follow_parent_not_flat_gnum(conn):
    """A block newly split from G2 follows G2's other blocks; a top-level long-running row must not come between them."""
    from app.view import _goal_rows
    NOW = T0 + timedelta(days=4)
    t = lambda h: f"2026-10-02T{h:02d}:00:00+00:00"  # noqa: E731
    apply_action(conn, "goal_create", {"title": "母题", "line": "团队协作", "gnum": "G2", "occurred_at": t(1)}, NOW, internal=True)
    apply_action(conn, "goal_create", {"title": "子一", "line": "团队协作", "gnum": "G2.1", "parent_gnum": "G2", "occurred_at": t(2)}, NOW, internal=True)
    apply_action(conn, "goal_create", {"title": "长期", "line": "团队协作", "long_term": True, "occurred_at": t(3)}, NOW)  # birth number, top level
    apply_action(conn, "goal_create", {"title": "子二", "line": "团队协作", "parent_gnum": "G2", "occurred_at": t(4)}, NOW)  # birth number, under G2
    apply_action(conn, "goal_create", {"title": "孙", "line": "团队协作", "parent_gnum": "G2.1", "occurred_at": t(5)}, NOW)
    titles = [g["title"] for g in _goal_rows(conn)]
    assert titles == ["母题", "子一", "孙", "子二", "长期"], titles


def test_top_level_follows_gnum_not_creation_time(conn):
    """Top level within a line sorts by number too: a backfilled goal with an early creation time must not jump ahead of
    one numbered before it. G numbers first, birth numbers numerically (C9 before C10); blocks still follow their parent."""
    from app.view import _goal_rows
    NOW = T0 + timedelta(days=4)
    t = lambda h: f"2026-10-02T{h:02d}:00:00+00:00"  # noqa: E731
    mk = lambda title, h, **kw: apply_action(conn, "goal_create", {"title": title, "line": "增长", "occurred_at": t(h), **kw}, NOW,  # noqa: E731
                                             internal="gnum" in kw)
    for i in range(1, 9):
        mk(f"占号{i}", 0, line="个人事项")  # use up C1–C8 so the next three get C9, C10, C11
    mk("先发号后立项", 9)      # C9
    mk("C10", 8)               # C10
    mk("补录立项最早", 1)      # C11: earliest creation time, still last
    mk("团队目标", 10, gnum="G5")
    mk("团队子块", 11, gnum="G5.1", parent_gnum="G5")
    mk("本地子块", 0, parent_gnum="G5")
    got = [g["title"] for g in _goal_rows(conn) if g["line"] == "增长"]
    assert got == ["团队目标", "团队子块", "本地子块", "先发号后立项", "C10", "补录立项最早"], got


def test_top_level_follows_birth_number_even_after_push(conn):
    """Top-level goals with a birth number sort by it and do not move when a push changes their display number: one
    created later but pushed first (getting the smaller G number) stays behind. Team goals without a birth number come first."""
    from app.view import _goal_rows
    NOW = T0 + timedelta(days=4)
    at = "2026-10-02T01:00:00+00:00"
    apply_action(conn, "goal_create", {"title": "甲", "line": "增长", "occurred_at": at}, NOW)   # C1
    apply_action(conn, "goal_create", {"title": "乙", "line": "增长", "occurred_at": at}, NOW)   # C2
    apply_action(conn, "goal_create", {"title": "丙", "line": "增长", "occurred_at": at}, NOW)   # C3, never pushed
    apply_action(conn, "goal_create", {"title": "团队上立的", "line": "增长", "gnum": "G50", "occurred_at": at}, NOW, internal=True)
    apply_action(conn, "goal_update", {"goal": "C2", "gnum": "G44"}, NOW)   # the second is pushed first
    apply_action(conn, "goal_update", {"goal": "C1", "gnum": "G45"}, NOW)   # the first is pushed later
    rows = [g for g in _goal_rows(conn) if g["line"] == "增长"]
    assert [(g["title"], g["gnum"], g["birth"]) for g in rows] == [
        ("团队上立的", "G50", None), ("甲", "G45", "C1"), ("乙", "G44", "C2"), ("丙", "C3", "C3")]


def test_long_term_rows_sink_to_bottom_of_their_line(conn):
    """Long-running rows sink to the bottom of their own line, sorted by number among themselves; other lines are unaffected."""
    from app.view import _goal_rows
    NOW = T0 + timedelta(days=4)
    mk = lambda title, **kw: apply_action(conn, "goal_create", {"title": title, "line": "团队协作",  # noqa: E731
                                                                "occurred_at": "2026-10-02T01:00:00+00:00", **kw}, NOW)
    mk("长期甲", long_term=True)   # C1
    mk("普通乙")                    # C2
    mk("长期丙", long_term=True)   # C3
    mk("普通丁")                    # C4
    mk("丁的子块", parent_gnum="C4")
    mk("增长的事", line="增长")     # a higher number, still in its own line
    rows = _goal_rows(conn)
    assert [g["title"] for g in rows if g["line"] == "团队协作"] == ["普通乙", "普通丁", "丁的子块", "长期甲", "长期丙"]
    assert [g["title"] for g in rows if g["line"] == "增长"] == ["增长的事"]


def test_siblings_follow_gnum_not_creation_time(conn):
    """G2.10 was created here first and got number 10 only when pushed; G2.9 was created later. Blocks under one
    parent still sort by number — G2.9 before G2.10 in the timeline and on the detail page — and unpushed ones go last."""
    from app.view import _goal_rows, goal_detail
    NOW = T0 + timedelta(days=4)
    t = lambda h, m=0: f"2026-10-02T{h:02d}:{m:02d}:00+00:00"  # noqa: E731
    apply_action(conn, "goal_create", {"title": "G2", "line": "团队协作", "gnum": "G2", "occurred_at": t(1)}, NOW, internal=True)
    apply_action(conn, "goal_create", {"title": "G2.10", "line": "团队协作", "gnum": "G2.10", "parent_gnum": "G2", "occurred_at": t(2)}, NOW, internal=True)
    for i in range(1, 10):
        apply_action(conn, "goal_create", {"title": f"G2.{i}", "line": "团队协作", "gnum": f"G2.{i}", "parent_gnum": "G2",
                                           "occurred_at": t(3, i)}, NOW, internal=True)
    apply_action(conn, "goal_create", {"title": "本地块", "line": "团队协作", "parent_gnum": "G2", "occurred_at": t(0)}, NOW)  # birth number, created earliest
    want = ["G2"] + [f"G2.{i}" for i in range(1, 11)] + ["本地块"]
    assert [g["title"] for g in _goal_rows(conn)] == want
    assert [c["title"] for c in goal_detail(conn, "G2", NOW)["children"]] == want[1:]


def test_abandon_without_reason_has_no_reason_on_detail(conn):
    # an empty "why abandoned" hides the field; the placeholder written when no reason was given is not a reason
    from app.view import goal_detail
    bare = apply_action(conn, "goal_create", {"title": "不写原因", "line": "个人事项", "occurred_at": T0.isoformat()}, T0)
    apply_action(conn, "goal_update", {"goal": bare.gnum, "status": "abandoned"}, T0 + timedelta(hours=1))
    why = apply_action(conn, "goal_create", {"title": "写了原因", "line": "个人事项", "occurred_at": T0.isoformat()}, T0)
    apply_action(conn, "goal_update", {"goal": why.gnum, "status": "abandoned", "reason": "并到别的目标里做了"}, T0 + timedelta(hours=1))
    now = T0 + timedelta(hours=2)
    assert goal_detail(conn, bare.gnum, now)["abandon_reason"] == ""
    assert goal_detail(conn, why.gnum, now)["abandon_reason"] == "并到别的目标里做了"
