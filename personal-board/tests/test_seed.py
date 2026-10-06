"""The fictional demo board: both languages seed cleanly on an empty board, dated relative to the day of seeding,
and show every feature the board has."""
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from app import settings
from app.seed import seed_demo
from app.store import open_db
from app.view import goal_detail, pending_entries, state, timeline
from tests.conftest import make_config

ROOT = Path(__file__).resolve().parents[1]
CJK = re.compile(r"[一-鿿]")
LA = ZoneInfo("America/Los_Angeles")
EVENING = datetime(2026, 10, 14, 19, 30, tzinfo=LA)   # a Wednesday evening: the whole of "today" has happened


def _seed(tmp_path, lang, now=EVENING, letter=None, **over):
    cfg = make_config(lang, **over)
    cfg["person"]["letter"] = letter or ("L" if lang == "zh" else "A")
    settings.use(cfg)
    conn = open_db(tmp_path / f"{lang}.sqlite")
    r = seed_demo(conn, lang, now)
    return conn, r


@pytest.mark.parametrize("lang", ["zh", "en"])
def test_demo_shows_every_feature(tmp_path, lang):
    conn, r = _seed(tmp_path, lang, team_board={"base_url": "", "token": ""})   # the default: no team board connected
    assert r["skipped"] == 0 and r["goals"] == 11
    now = EVENING
    s = state(conn, now.date(), now)
    P = "L" if lang == "zh" else "A"
    goals = {g["gnum"]: g for ln in s["lines"] for g in ln["goals"]}
    # the owner's team goals, the pushed one with both numbers, the local ones with birth numbers; G3 is finished
    assert set(goals) == {"G1", "G2", "G5", "G6", "G6.2", "G6.3", f"{P}1", f"{P}2", f"{P}3", f"{P}5"}
    assert goals["G2"]["birth"] == f"{P}4" and goals["G2"]["source"] == "team"
    assert goal_detail(conn, "G3", now)["goal"]["status"] == "done" and goal_detail(conn, "G3", now)["goal"]["done_what"]
    assert all(g["next_step"] for g in goals.values() if not g["point"]), "every goal in progress has a next step"
    assert goals["G6.3"]["blocker"] and goals["G6.2"]["open_stages"] and not goals["G5"]["has_stages"]
    assert goals[f"{P}1"]["long_term"] and goals[f"{P}1"]["version_name"].endswith("1.2.1")
    assert len(goal_detail(conn, f"{P}1", now)["releases"]) == 4                 # the changelog of the long-running row
    assert [ln["name"] for ln in s["lines"] if ln["personal"]] == [goals[f"{P}3"]["line"]]
    # 2–3 unpushed entries on the goal that is not on the team board yet; everything else on team lines is pushed
    pend = pending_entries(conn)
    assert s["header"]["pending_count"] == 3 and {e["gnum"] for e in pend} == {f"{P}5"}
    assert conn.execute("SELECT COUNT(*) FROM entries WHERE sync='pushed'").fetchone()[0] > 30
    # the monthly point task: last month's occurrence done, this month's still open (overdue on the 14th)
    occ = goal_detail(conn, f"{P}2", now)["point"]["occ"]
    assert [o["state"] for o in occ][:2] == ["done", "overdue"] and s["points_due"]["items"]
    # a goal running late: its first plan was yesterday, the plan was moved once
    g2 = conn.execute("SELECT due, baseline_due FROM goals WHERE gnum='G2'").fetchone()
    assert g2["baseline_due"] == "2026-10-13" and g2["due"] == "2026-10-15"
    # the last four days each carry 10–25 entries spread over the working hours, from several conversations in both tools
    for back in range(4):
        day = state(conn, (now - timedelta(days=back)).date(), now)
        assert 10 <= day["entry_count"] <= 25, (back, day["entry_count"])
        assert len(day["hours"]) >= 6
    kinds = {r[0] for r in conn.execute("SELECT DISTINCT kind FROM entries")}
    assert {"start", "result", "wrap", "note", "digest", "stage_start", "stage_end", "goal_create", "due", "complete", "point_done"} <= kinds
    assert {r[0] for r in conn.execute("SELECT DISTINCT tool FROM entries WHERE tool<>''")} == {"claude", "codex"}
    assert conn.execute("SELECT COUNT(DISTINCT task) FROM entries WHERE task<>''").fetchone()[0] >= 8
    assert len(s["todos"]) == 3 and len(s["notes"]) == 2
    assert not conn.execute("SELECT COUNT(*) FROM entries WHERE julianday(recorded_at) - julianday(occurred_at) > 0.04").fetchone()[0], \
        "seeded entries are not shown as backfilled"
    week = timeline(conn, now - timedelta(days=7), now, now)["rows"]
    assert {"G1", "G2", "G3", "G5", "G6", "G6.2", "G6.3"} <= {row["gnum"] for row in week}
    text = " ".join(str(v) for tb in ("goals", "entries", "todos", "notes") for row in conn.execute(f"SELECT * FROM {tb}") for v in tuple(row))
    assert bool(CJK.search(text)) == (lang == "zh")                              # the English set has no Chinese in it
    assert state(conn, now.date(), now)["header"]["demo"] is True


def test_seed_is_relative_to_today_and_never_in_the_future(tmp_path):
    early = datetime(2026, 3, 1, 6, 15, tzinfo=LA)        # the 1st of a month, before work: today is still empty
    conn, r = _seed(tmp_path, "en", now=early)
    assert r["skipped"] == 0
    assert conn.execute("SELECT MAX(occurred_at) FROM entries").fetchone()[0] <= early.astimezone(ZoneInfo("UTC")).isoformat()
    s = state(conn, early.date(), early)
    assert s["entry_count"] == 0 and state(conn, (early - timedelta(days=1)).date(), early)["entry_count"] >= 10
    assert [i["status"] for i in s["points_due"]["items"]] == ["due today"]     # this month's payment is due today at 10:00
    occ = goal_detail(conn, "A2", early)["point"]["occ"]
    assert [(o["state"], o["at"][:10]) for o in occ][:2] == [("done", "2026-02-01"), ("upcoming", "2026-03-01")]


def test_seed_refuses_a_board_with_data_and_unknown_languages(tmp_path):
    conn, _ = _seed(tmp_path, "zh")
    with pytest.raises(ValueError, match="空库"):
        seed_demo(conn, "zh", EVENING)
    with pytest.raises(ValueError):
        seed_demo(open_db(tmp_path / "x.sqlite"), "fr", EVENING)


def test_seed_text_follows_lang_but_names_follow_config(tmp_path):
    """`seed --lang en` on a Chinese config: the story is English, lines and stages are the configured (Chinese) ones."""
    cfg = make_config("zh")
    settings.use(cfg)
    conn = open_db(tmp_path / "mixed.sqlite")
    assert seed_demo(conn, "en", EVENING)["skipped"] == 0
    assert {r[0] for r in conn.execute("SELECT DISTINCT line FROM goals")} <= set(settings.line_names())
    assert conn.execute("SELECT title FROM goals WHERE gnum='G1'").fetchone()[0] == "Launch paid membership"


@pytest.mark.parametrize("lang", ["zh", "en"])
def test_cli_init_seed(tmp_path, lang):
    env = dict(os.environ, PERSONAL_BOARD_DATA=str(tmp_path / "cli"))
    run = lambda *a: subprocess.run([sys.executable, str(ROOT / "board"), *a], env=env, capture_output=True, text=True)  # noqa: E731
    assert run("status").returncode == 1                                         # not set up yet: says so, does not guess
    out = run("init", "--lang", lang, "--name", "林夏" if lang == "zh" else "Alex", "--letter", "L" if lang == "zh" else "A", "--port", "1")
    assert out.returncode == 0, out.stderr
    assert run("init", "--lang", lang).returncode == 1                           # an existing config is not overwritten silently
    out = run("seed")
    assert out.returncode == 0, out.stderr
    assert bool(CJK.search(out.stdout)) == (lang == "zh")
    assert run("seed").returncode == 1                                           # only on an empty board
    assert run("reset").returncode == 0 and (tmp_path / "cli" / "board.sqlite").stat().st_size > 0   # dry run touches nothing
    conn = open_db(tmp_path / "cli" / "board.sqlite")
    assert conn.execute("SELECT COUNT(*) FROM goals").fetchone()[0] == 11
    assert run("reset", "--execute").returncode == 0
    assert open_db(tmp_path / "cli" / "board.sqlite").execute("SELECT COUNT(*) FROM goals").fetchone()[0] == 0
    assert list((tmp_path / "cli" / "backups").glob("board-*.sqlite"))
