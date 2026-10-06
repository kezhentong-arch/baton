"""Birth numbers: a goal created here gets the owner's letter + a sequence; the number never changes and is
never reused, and it still finds the goal after a push switched the display number to the team's."""
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import pytest

import app.team as team
from app import settings
from app.actions import ActionError, apply_action
from app.store import db_path, get_meta, open_db
from app.view import goal_detail, pending_entries

NOW = datetime(2026, 10, 3, 17, 0, tzinfo=timezone.utc)


def _db(path: Path, person: str = "linxia"):
    c = open_db(path)
    with c:
        c.execute("INSERT INTO meta(key, value) VALUES('person', ?)", (person,))
    return c


def _team_goal(**over) -> dict:
    return {"id": 31, "gnum": "G31", "source": "C1", "title": "新块", "line": "团队协作", "status": "进行中",
            "owner": "林夏", "parent_id": None, "sample": False, "long_term": False, "baseline_due": "", "latest_due": "", **over}


def test_create_issues_configured_letter_and_sequence(tmp_path, use_config):
    c = _db(tmp_path / "c.sqlite")
    a = apply_action(c, "goal_create", {"title": "甲", "line": "团队协作"}, NOW)
    b = apply_action(c, "goal_create", {"title": "乙", "line": "个人事项"}, NOW)
    assert (a.gnum, b.gnum) == ("C1", "C2")
    assert c.execute("SELECT birth FROM goals WHERE id=?", (a.goal_id,)).fetchone()[0] == "C1"
    # the letter is whatever the config says — any capital letter except the reserved G and E
    use_config(person={"id": "ben", "name": "周行", "letter": "Z"})
    z = _db(tmp_path / "z.sqlite", "ben")
    assert apply_action(z, "goal_create", {"title": "甲", "line": "增长"}, NOW).gnum == "Z1"
    assert z.execute("SELECT owner FROM goals").fetchone()[0] == "ben"
    for bad in ("G", "E", "ab", "x", ""):
        with pytest.raises(settings.ConfigError):
            use_config(person={"id": "p", "name": "p", "letter": bad})


def test_explicit_gnum_gets_no_birth(tmp_path):
    """Example E numbers and goals given an explicit number get no birth number and do not use one up."""
    c = _db(tmp_path / "c.sqlite")
    apply_action(c, "goal_create", {"title": "示例", "line": "增长", "gnum": "E1"}, NOW, internal=True)
    assert c.execute("SELECT birth FROM goals WHERE gnum='E1'").fetchone()[0] is None
    assert apply_action(c, "goal_create", {"title": "真", "line": "增长"}, NOW).gnum == "C1"


def test_birth_still_finds_goal_after_rename_and_parent_stored_as_display(tmp_path):
    c = _db(tmp_path / "c.sqlite")
    p = apply_action(c, "goal_create", {"title": "母题", "line": "团队协作"}, NOW)
    apply_action(c, "goal_update", {"goal": "C1", "gnum": "G2.11"}, NOW)
    # after the push switched it to a G number, the birth number still logs and still opens the detail
    apply_action(c, "log", {"goal": "C1", "text": "按出生号记一条"}, NOW)
    assert goal_detail(c, "C1")["goal"]["gnum"] == "G2.11" and goal_detail(c, "C1")["goal"]["birth"] == "C1"
    # a block whose parent is given as a birth number stores the display number, so the tree links up
    k = apply_action(c, "goal_create", {"title": "块", "line": "团队协作", "parent_gnum": "C1"}, NOW)
    assert c.execute("SELECT parent_gnum FROM goals WHERE id=?", (k.goal_id,)).fetchone()[0] == "G2.11"
    assert p.goal_id != k.goal_id
    # a display number cannot be changed into someone else's birth number
    with pytest.raises(ActionError):
        apply_action(c, "goal_update", {"goal": k.gnum, "gnum": "C1"}, NOW)


def test_pending_entries_carry_birth_for_push(tmp_path):
    """The create push at wrap-up carries source = the birth number, so the unpushed list must show it."""
    c = _db(tmp_path / "c.sqlite")
    apply_action(c, "goal_create", {"title": "新事", "line": "增长"}, NOW)
    apply_action(c, "goal_update", {"goal": "C1", "gnum": "G31"}, NOW)
    pend = pending_entries(c)
    assert pend and all(e["birth"] == "C1" and e["gnum"] == "G31" for e in pend)


def test_reset_keeps_counting(tmp_path):
    """After emptying the board, numbers keep counting instead of starting at 1 again."""
    from app.seed import reset_main
    c = _db(db_path(False))
    for title in ("一", "二", "三"):
        apply_action(c, "goal_create", {"title": title, "line": "个人事项"}, NOW)
    c.close()
    reset_main(NOW)
    c = open_db(db_path(False))
    assert c.execute("SELECT COUNT(*) FROM goals").fetchone()[0] == 0
    assert apply_action(c, "goal_create", {"title": "四", "line": "个人事项"}, NOW).gnum == "C4"


def test_pull_claims_row_by_source_birth(tmp_path):
    """Pushed but pulled before the display number was switched: the team board remembers source C1, and the
    local row is claimed by it instead of a second row being inserted."""
    c = _db(tmp_path / "c.sqlite")
    apply_action(c, "goal_create", {"title": "新块", "line": "团队协作"}, NOW)
    with mock.patch.object(team, "fetch_state", return_value={"goals": [_team_goal()]}):
        assert team.pull(c, NOW)["ok"] is True
    rows = c.execute("SELECT gnum, birth, team_id FROM goals").fetchall()
    assert [tuple(r) for r in rows] == [("G31", "C1", 31)]
    assert get_meta(c, "team_pull_error") == ""


def test_two_connections_creating_at_once_get_different_births(tmp_path):
    """Two conversations (two connections) creating goals at once: the second waits for the write lock and
    neither computes the same number nor fails with an obscure unique-key error."""
    import threading
    path = tmp_path / "c.sqlite"
    _db(path).close()
    out: list[str] = []
    errs: list[Exception] = []
    barrier = threading.Barrier(2)

    def go(i: int) -> None:
        conn = open_db(path)
        barrier.wait()
        try:
            for k in range(10):
                out.append(apply_action(conn, "goal_create", {"title": f"{i}-{k}", "line": "个人事项"}, NOW).gnum)
        except Exception as e:   # noqa: BLE001
            errs.append(e)
        finally:
            conn.close()

    ts = [threading.Thread(target=go, args=(i,)) for i in range(2)]
    for th in ts:
        th.start()
    for th in ts:
        th.join()
    assert not errs and len(out) == 20 and len(set(out)) == 20


def test_pull_renaming_by_source_carries_children(tmp_path):
    """Claimed by source and renamed to its G number: a block not yet pushed follows instead of being orphaned."""
    c = _db(tmp_path / "c.sqlite")
    apply_action(c, "goal_create", {"title": "母题", "line": "团队协作"}, NOW)
    apply_action(c, "goal_create", {"title": "块", "line": "团队协作", "parent_gnum": "C1"}, NOW)
    with mock.patch.object(team, "fetch_state", return_value={"goals": [_team_goal(title="母题")]}):
        team.pull(c, NOW)
    assert c.execute("SELECT parent_gnum FROM goals WHERE birth='C2'").fetchone()[0] == "G31"
    assert goal_detail(c, "C2")["parent"]["gnum"] == "G31"


def test_find_is_case_insensitive(tmp_path):
    c = _db(tmp_path / "c.sqlite")
    apply_action(c, "goal_create", {"title": "甲", "line": "个人事项"}, NOW)
    apply_action(c, "goal_update", {"goal": "C1", "gnum": "G40"}, NOW)
    assert goal_detail(c, "c1")["goal"]["gnum"] == "G40" and goal_detail(c, "g40")["goal"]["birth"] == "C1"
