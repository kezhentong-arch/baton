from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.actions import ActionError, apply_action, open_stages
from app.store import open_db

NOW = datetime(2026, 10, 2, 16, 0, tzinfo=timezone.utc)  # 10-02 09:00 in Los Angeles


@pytest.fixture
def conn(tmp_path: Path):
    c = open_db(tmp_path / "t.sqlite")
    c.execute("INSERT INTO meta(key, value) VALUES('person','linxia')")
    return c


def t(minutes: int) -> str:
    return (NOW + timedelta(minutes=minutes)).isoformat()


def test_parallel_stages_end_independently(conn):
    r = apply_action(conn, "goal_create", {"title": "个人看板", "line": "团队协作"}, NOW)
    g = r.gnum
    apply_action(conn, "stage_start", {"goal": g, "stage": "产品"}, NOW)
    apply_action(conn, "stage_start", {"goal": g, "stage": "开发", "occurred_at": t(10)}, NOW + timedelta(minutes=10))
    assert set(open_stages(conn, r.goal_id)) == {"产品", "开发"}
    apply_action(conn, "stage_end", {"goal": g, "stage": "产品", "occurred_at": t(20)}, NOW + timedelta(minutes=20))
    assert set(open_stages(conn, r.goal_id)) == {"开发"}


def test_duplicate_start_and_backfill_before_create_rejected(conn):
    r = apply_action(conn, "goal_create", {"title": "x", "line": "增长"}, NOW)
    apply_action(conn, "stage_start", {"goal": r.gnum, "stage": "开发"}, NOW)
    with pytest.raises(ActionError, match="已经在进行中"):
        apply_action(conn, "stage_start", {"goal": r.gnum, "stage": "开发"}, NOW + timedelta(minutes=1))
    with pytest.raises(ActionError, match="早于目标立项"):
        apply_action(conn, "log", {"goal": r.gnum, "text": "早了", "occurred_at": t(-60)}, NOW)
    with pytest.raises(ActionError, match="缺必填"):
        apply_action(conn, "stage_end", {"goal": r.gnum}, NOW)


def test_sync_pending_only_on_team_lines(conn):
    a = apply_action(conn, "goal_create", {"title": "团队的", "line": "产品"}, NOW)
    b = apply_action(conn, "goal_create", {"title": "自己的", "line": "个人事项"}, NOW)
    apply_action(conn, "log", {"goal": a.gnum, "text": "页面跑通", "kind": "result"}, NOW)
    rows = {r["id"]: r["sync"] for r in conn.execute("SELECT id, sync FROM entries")}
    assert rows[a.ids[0]] == "pending" and rows[b.ids[0]] is None
    assert [s for i, s in rows.items() if i not in (a.ids[0], b.ids[0])] == [None]
    apply_action(conn, "sync_mark", {"entry_ids": [a.ids[0]], "status": "pushed", "team_ref": "ev 131"}, NOW)
    assert conn.execute("SELECT sync, team_ref FROM entries WHERE id=?", (a.ids[0],)).fetchone()[:] == ("pushed", "ev 131")
    with pytest.raises(ActionError, match="不是待推"):
        apply_action(conn, "sync_mark", {"entry_ids": [b.ids[0]], "status": "pushed"}, NOW)


def test_complete_closes_open_stages_and_blocks_new_ones(conn):
    r = apply_action(conn, "goal_create", {"title": "x", "line": "团队协作"}, NOW)
    apply_action(conn, "stage_start", {"goal": r.gnum, "stage": "测试"}, NOW)
    res = apply_action(conn, "complete", {"goal": r.gnum, "occurred_at": t(5)}, NOW + timedelta(minutes=5))
    kinds = [row["kind"] for row in conn.execute("SELECT kind FROM entries WHERE id IN (%s)" % ",".join(map(str, res.ids)))]
    assert sorted(kinds) == ["complete", "stage_end"]
    assert open_stages(conn, r.goal_id) == {}
    with pytest.raises(ActionError, match="已经完成"):
        apply_action(conn, "stage_start", {"goal": r.gnum, "stage": "开发"}, NOW + timedelta(minutes=6))


def test_rename_after_push_keeps_children(conn):
    p = apply_action(conn, "goal_create", {"title": "母题", "line": "产品"}, NOW)
    c = apply_action(conn, "goal_create", {"title": "块", "line": "产品", "parent_gnum": p.gnum}, NOW)
    assert p.gnum == "C1"   # birth number: the owner's letter + a sequence
    apply_action(conn, "goal_update", {"goal": p.gnum, "gnum": "G20"}, NOW)
    assert conn.execute("SELECT parent_gnum FROM goals WHERE id=?", (c.goal_id,)).fetchone()[0] == "G20"


def test_digest_kind_accepted_and_labelled(conn):
    """A digest is the fifth kind of note: accepted, labelled as such, and not an event that goes to the team board."""
    from app.view import goal_detail
    r = apply_action(conn, "goal_create", {"title": "个人手册持续沉淀", "line": "团队协作", "long_term": True}, NOW, internal=True)
    apply_action(conn, "log", {"goal": r.gnum, "kind": "digest", "text": "手册 1.2.0：加沉淀记录", "task": "t", "tool": "claude"}, NOW)
    ents = [e for d in goal_detail(conn, r.gnum)["days"] for e in d["entries"]]
    e = next(e for e in ents if e["kind"] == "digest")
    assert e["kind_label"] == "沉淀" and e["sync"] is None
    with pytest.raises(ActionError):
        apply_action(conn, "log", {"goal": r.gnum, "kind": "deposit", "text": "x"}, NOW)


def test_entries_of_no_push_goal_are_not_pending(conn):
    # a long-running row whose creation is marked "not pushed": its later stage entries stay out of the unpushed list
    r = apply_action(conn, "goal_create", {"title": "个人看板持续维护", "line": "团队协作", "long_term": True}, NOW)
    apply_action(conn, "sync_mark", {"entry_ids": [r.ids[0]], "status": "skip", "team_ref": "团队看板不展示"}, NOW)
    s = apply_action(conn, "stage_start", {"goal": r.gnum, "stage": "开发"}, NOW)
    d = apply_action(conn, "goal_update", {"goal": r.gnum, "due": "2026-10-03", "reason": "试"}, NOW)
    rows = {row["id"]: row["sync"] for row in conn.execute("SELECT id, sync FROM entries")}
    assert rows[s.ids[0]] is None and rows[d.ids[0]] is None
    # a team-line goal whose creation is still unpushed behaves as usual: its stage entries are unpushed too
    p = apply_action(conn, "goal_create", {"title": "还没推的", "line": "团队协作"}, NOW)
    s2 = apply_action(conn, "stage_start", {"goal": p.gnum, "stage": "开发"}, NOW)
    assert conn.execute("SELECT sync FROM entries WHERE id=?", (s2.ids[0],)).fetchone()[0] == "pending"


def test_baseline_due_is_the_first_plan_and_stays(conn):
    """Delay is measured from the first plan ever set: a plan given at creation is the baseline and later changes
    leave it; with no plan at creation, the first one set becomes the baseline."""
    r = apply_action(conn, "goal_create", {"title": "定了计划的", "line": "增长", "due": "2026-10-05"}, NOW)
    apply_action(conn, "goal_update", {"goal": r.gnum, "due": "2026-10-09 08:00", "reason": "推迟"}, NOW)
    row = conn.execute("SELECT due, baseline_due FROM goals WHERE id=?", (r.goal_id,)).fetchone()
    assert (row["due"], row["baseline_due"]) == ("2026-10-09 08:00", "2026-10-05")
    r2 = apply_action(conn, "goal_create", {"title": "没定计划的", "line": "增长"}, NOW)
    apply_action(conn, "goal_update", {"goal": r2.gnum, "due": "2026-10-07"}, NOW)
    apply_action(conn, "goal_update", {"goal": r2.gnum, "due": "2026-10-08"}, NOW)
    assert conn.execute("SELECT baseline_due FROM goals WHERE id=?", (r2.goal_id,)).fetchone()[0] == "2026-10-07"


def test_summary_edits_on_pushed_goal_merge_into_one_pending_entry(conn):
    """Editing the summary of a pushed goal twice must leave one unpushed "summary edited" entry, not two: both
    would push the latest text and the team board would reject the second as "nothing to change" forever."""
    g = apply_action(conn, "goal_create", {"title": "x", "line": "团队协作"}, NOW)
    ids = [r[0] for r in conn.execute("SELECT id FROM entries WHERE sync='pending'")]
    apply_action(conn, "sync_mark", {"entry_ids": ids, "status": "pushed"}, NOW)
    apply_action(conn, "goal_update", {"goal": g.gnum, "what": "X1"}, NOW)
    apply_action(conn, "goal_update", {"goal": g.gnum, "what": "X2"}, NOW + timedelta(minutes=1))
    rows = conn.execute("SELECT text FROM entries WHERE kind='summary' AND sync='pending'").fetchall()
    assert [r[0] for r in rows] == ["改「做什么」：X2"]


def test_version_card_is_highest_number_not_latest_release(conn):
    """The badge is always the highest-numbered version and the changelog sorts the same way: two conversations
    closing v1.3.2 and then v1.3.1 must not leave the badge at v1.3.1."""
    from app.view import goal_detail
    g = apply_action(conn, "goal_create", {"title": "看板持续维护", "line": "团队协作", "long_term": True}, NOW).gnum
    apply_action(conn, "release", {"goal": g, "version": "v1.3.2", "text": "网址可点"}, NOW)
    apply_action(conn, "release", {"goal": g, "version": "v1.3.1", "text": "今天线不漏画"}, NOW + timedelta(minutes=6))
    d = goal_detail(conn, g)
    assert d["goal"]["version_name"] == "v1.3.2"
    assert [r["version"] for r in d["releases"]] == ["v1.3.2", "v1.3.1"]
    apply_action(conn, "release", {"goal": g, "version": "v1.3.10", "text": "按数字比"}, NOW + timedelta(minutes=7))
    assert goal_detail(conn, g)["goal"]["version_name"] == "v1.3.10"   # 1.3.10 > 1.3.2: compared as numbers, not text
