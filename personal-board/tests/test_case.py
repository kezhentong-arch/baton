"""Case packs: export → load into an empty board keeps everything, unpushed becomes "not pushed", a non-empty board is
refused, no particular person is recognised, a loaded board refuses team pulls; reset backs up first and keeps the owner."""
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import pytest

from app import case, settings, team
from app.actions import apply_action
from app.seed import reset_main
from app.store import db_path, get_meta, open_db
from app.view import goal_detail, state, timeline

NOW = datetime(2026, 10, 2, 16, 0, tzinfo=timezone.utc)
ROOT = Path(__file__).resolve().parents[1]


def _filled(path):
    conn = open_db(path)
    with conn:
        conn.execute("INSERT INTO meta(key, value) VALUES('person', 'linxia')")
    apply_action(conn, "goal_create", {"title": "新协作方式落地", "line": "团队协作", "gnum": "G5"}, NOW, internal=True)
    apply_action(conn, "stage_start", {"goal": "G5", "stage": "业务", "task": "t", "tool": "claude"}, NOW)  # team line → unpushed
    apply_action(conn, "goal_create", {"title": "私事", "line": "个人事项"}, NOW)
    apply_action(conn, "todo_add", {"text": "待办一条", "goal": "G5"}, NOW)
    apply_action(conn, "note_add", {"text": "口述草稿"}, NOW)
    return conn


def test_export_import_roundtrip_marks_pending_skip_and_refuses_nonempty(tmp_path):
    src = _filled(tmp_path / "src.sqlite")
    data = case.export_case(src, NOW)
    assert data["format"] == 1 and data["lang"] == "zh" and data["person"]["name"] == "林夏"
    assert set(data["tables"]) == {"goals", "entries", "todos"}  # dictations are not exported
    assert [ln["name"] for ln in data["config"]["lines"]] == settings.line_names()
    assert json.dumps(data, ensure_ascii=False)  # serialisable
    dst = open_db(tmp_path / "dst.sqlite")
    counts = case.import_case(dst, data, NOW)
    assert counts == {"goals": 2, "entries": len(data["tables"]["entries"]), "todos": 1}
    assert dst.execute("SELECT COUNT(*) FROM entries WHERE sync='pending'").fetchone()[0] == 0
    assert dst.execute("SELECT COUNT(*) FROM entries WHERE sync='skip'").fetchone()[0] >= 1
    assert dst.execute("SELECT COUNT(*) FROM notes").fetchone()[0] == 0
    assert "林夏的看板副本" in (get_meta(dst, "case") or "")
    assert state(dst, NOW.date(), NOW)["header"]["case"].startswith("林夏的看板副本")
    with pytest.raises(ValueError, match="reset"):       # a second load: the board is no longer empty
        case.import_case(dst, data, NOW)
    with pytest.raises(ValueError):                      # not a pack at all
        case.import_case(open_db(tmp_path / "x.sqlite"), {"format": 2}, NOW)


def test_any_pack_loads_and_displays(tmp_path, use_config):
    """A hand-made pack from a different board — other owner, other language, lines and stages this config does not
    have, an older column naming, a zone label instead of an IANA name — loads into an empty board and renders."""
    use_config("en")
    at = "2026-09-30T17:00:00+00:00"
    pack = {
        "format": 1, "lang": "zh", "person": {"id": "someone", "name": "某人", "letter": "M"}, "exported_at": NOW.isoformat(),
        "zone_aliases": {"东京": "Asia/Tokyo"},
        "tables": {
            "goals": [
                {"id": 3, "gnum": "G7", "birth": "M2", "line": "研发", "title": "接口改造", "owner": "someone", "status": "active",
                 "source": "company", "company_id": 70, "created_at": at, "updated_at": at, "next_step": "联调", "no_such_column": 1},
                {"id": 4, "gnum": "M5", "birth": "M5", "line": "杂事", "title": "每月对账", "owner": "someone", "status": "active",
                 "source": "local", "created_at": at, "updated_at": at, "point_at": "2026-10-01T01:00:00+00:00",
                 "point_zone": "东京", "point_repeat": "monthly"},
                {"id": 5, "gnum": "M6", "birth": "M6", "line": "杂事", "title": "一次性的事", "owner": "someone", "status": "active",
                 "source": "local", "created_at": at, "updated_at": at, "point_at": "2026-10-05T01:00:00+00:00", "point_zone": "不认识的时区"},
            ],
            "entries": [
                {"id": 1, "goal_id": 3, "kind": "goal_create", "text": "立项：接口改造", "tool": "claude", "occurred_at": at,
                 "recorded_at": at, "sync": "pushed", "company_ref": "ev 9", "task": None, "void_reason": None},
                {"id": 2, "goal_id": 3, "stage": "联调", "kind": "stage_start", "text": "开始「联调」环节", "tool": "codex",
                 "occurred_at": at, "recorded_at": at, "sync": "pending"},
                {"id": 3, "goal_id": 3, "stage": "联调", "kind": "result", "text": "接口通了", "task": "接口改造", "tool": "codex",
                 "occurred_at": at, "recorded_at": at, "company_ref": None, "synced_at": None, "voided_at": None},
            ],
            "todos": [{"id": 1, "goal_id": 3, "text": "补文档", "created_at": at}],
        },
    }
    f = tmp_path / "pack.json"
    f.write_text(json.dumps(pack, ensure_ascii=False), encoding="utf-8")
    data = case.load_case_file(f)
    assert case.missing_names(data) == {"lines": ["杂事", "研发"], "stages": ["联调"]}
    conn = open_db(tmp_path / "dst.sqlite")
    assert case.import_case(conn, data, NOW) == {"goals": 3, "entries": 3, "todos": 1}
    g = conn.execute("SELECT source, team_id FROM goals WHERE gnum='G7'").fetchone()
    assert (g["source"], g["team_id"]) == ("team", 70)                         # older column names are understood
    assert [r[0] for r in conn.execute("SELECT sync FROM entries ORDER BY id")] == ["pushed", "skip", None]
    assert [r[0] for r in conn.execute("SELECT point_zone FROM goals WHERE point_at IS NOT NULL ORDER BY id")] == \
        ["Asia/Tokyo", "America/Los_Angeles"]                                  # alias → IANA; unknown → the loader's main zone
    s = state(conn, NOW.date(), NOW)
    assert s["header"]["case"] == "a copy of 某人's board (exported 10-02 09:00 (LA))" and s["header"]["pending_count"] == 0
    assert [ln["name"] for ln in s["lines"]] == ["Product", "Growth", "Operations", "Team", "Personal", "杂事", "研发"]
    assert [g["gnum"] for ln in s["lines"] if ln["name"] == "研发" for g in ln["goals"]] == ["G7"]
    d = goal_detail(conn, "M2", NOW)                                           # the pack's own birth numbers still work
    assert d["goal"]["open_stages"] == ["联调"] and d["stages"][0]["color"] in settings.STAGE_COLORS    # a steady colour, not grey
    assert s["stage_colors"]["联调"] == d["stages"][0]["color"]                  # and the legend lists it
    rows = timeline(conn, datetime(2026, 9, 28, tzinfo=timezone.utc), datetime(2026, 10, 8, tzinfo=timezone.utc), NOW)["rows"]
    assert {r["gnum"] for r in rows} == {"G7", "M5", "M6"}                     # both point tasks have a moment inside this window
    broken = dict(pack, tables=dict(pack["tables"], entries=[{"id": 9, "goal_id": 999, "kind": "note", "occurred_at": at, "recorded_at": at}]))
    empty = open_db(tmp_path / "broken.sqlite")
    with pytest.raises(ValueError, match="nothing was written"):               # an entry pointing at no goal: refused as a whole
        case.import_case(empty, broken, NOW)
    assert empty.execute("SELECT COUNT(*) FROM goals").fetchone()[0] == 0
    # the loader's own numbering is untouched by the pack's letter
    assert apply_action(conn, "goal_create", {"title": "Mine", "line": "Personal"}, NOW).gnum == "C1"


def test_adopt_config_takes_lines_and_stages_from_the_pack(tmp_path, use_config):
    src = _filled(tmp_path / "src.sqlite")
    data = case.export_case(src, NOW)
    use_config("en")
    settings.save_config(settings.active())
    assert case.missing_names(data)["lines"]
    case.adopt_config(data)
    assert settings.line_names() == ["产品", "增长", "运营", "团队协作", "个人事项"] and settings.lang() == "en"
    assert settings.load_config()["stages"][0]["name"] == "业务"
    assert case.missing_names(data) == {"lines": [], "stages": []}
    with pytest.raises(ValueError):
        case.adopt_config({"format": 1, "tables": {}})
    # a pack without a config block (the minimal format): lines and stages are read off its rows; default names keep
    # their usual order, and the loader's personal line stays
    use_config("en")
    bare = {"format": 1, "person": "linxia", "exported_at": NOW.isoformat(), "tables": {
        "goals": [{"id": 1, "line": "团队协作"}, {"id": 2, "line": "产品"}],
        "entries": [{"goal_id": 1, "stage": "测试"}, {"goal_id": 1, "stage": "业务"}, {"goal_id": 2, "stage": None}], "todos": []}}
    case.adopt_config(bare)
    assert [(ln["name"], ln["personal"]) for ln in settings.lines()] == [("产品", False), ("团队协作", False), ("Personal", True)]
    assert settings.stage_names() == ["业务", "测试"] and settings.stage_color("业务") == settings.STAGE_COLORS[0]
    assert case.case_label(bare).startswith("a copy of linxia's board")


def test_cli_export_then_seed_case(tmp_path):
    """./board export-case FILE on one board, ./board seed --case FILE on another empty one."""
    def run(home, *args):
        env = dict(os.environ, PERSONAL_BOARD_DATA=str(tmp_path / home))
        return subprocess.run([sys.executable, str(ROOT / "board"), *args], env=env, capture_output=True, text=True)
    assert run("a", "init", "--lang", "en", "--name", "Alex", "--letter", "A", "--port", "1").returncode == 0
    assert run("a", "seed").returncode == 0
    pack = tmp_path / "alex.json"
    out = run("a", "export-case", str(pack))
    assert out.returncode == 0 and pack.is_file(), out.stderr
    data = json.loads(pack.read_text(encoding="utf-8"))
    assert data["lang"] == "en" and data["person"]["name"] == "Alex" and len(data["tables"]["goals"]) == 11
    assert run("b", "init", "--lang", "zh", "--name", "读者", "--letter", "R", "--port", "1").returncode == 0
    out = run("b", "seed", "--case", str(pack), "--adopt-config")
    assert out.returncode == 0, out.stderr
    assert "Alex" in out.stdout
    again = run("b", "seed", "--case", str(pack))
    assert again.returncode == 1 and "reset" in again.stderr
    conn = open_db(tmp_path / "b" / "board.sqlite")
    assert conn.execute("SELECT COUNT(*) FROM goals").fetchone()[0] == 11
    assert conn.execute("SELECT COUNT(*) FROM entries WHERE sync='pending'").fetchone()[0] == 0
    assert (tmp_path / "b" / "practice.sqlite").exists()
    assert json.loads((tmp_path / "b" / "config.json").read_text(encoding="utf-8"))["lines"][0]["name"] == "Product"


def test_reset_backs_up_then_empties_and_keeps_person(tmp_path):
    conn = open_db(db_path(False))
    with conn:
        conn.execute("INSERT INTO meta(key, value) VALUES('person', 'ben')")
    apply_action(conn, "goal_create", {"title": "样例里的", "line": "个人事项"}, NOW)
    conn.close()
    r = reset_main(NOW)
    backups = settings.data_dir() / "backups"
    assert r["backup"] and backups.is_dir()
    b = open_db(backups / r["backup"].split("/")[-1])
    assert b.execute("SELECT COUNT(*) FROM goals").fetchone()[0] == 1  # still in the backup
    m = open_db(db_path(False))
    assert m.execute("SELECT COUNT(*) FROM goals").fetchone()[0] == 0 and get_meta(m, "person") == "ben"
    assert db_path(True).exists()


def test_case_db_refuses_team_pull(tmp_path):
    """A board loaded from a pack does not pull team goals: pulling as me would mix my goals into someone else's board."""
    src = _filled(tmp_path / "src.sqlite")
    dst = open_db(tmp_path / "dst.sqlite")
    case.import_case(dst, case.export_case(src, NOW), NOW)
    payload = {"goals": [{"id": 24, "gnum": "G2.8", "title": "别的目标", "line": "团队协作", "status": "进行中",
                          "owner": "林夏", "parent_id": None, "sample": False, "long_term": False, "baseline_due": "", "latest_due": ""}]}
    with mock.patch.object(team, "fetch_state", return_value=payload) as fetch:
        r = team.pull(dst, NOW)
    assert not r["ok"] and "样例" in r["error"] and not fetch.called
    assert dst.execute("SELECT COUNT(*) FROM goals WHERE gnum='G2.8'").fetchone()[0] == 0
    assert not (get_meta(dst, "team_pull_error") or "")   # an expected state, not a failed pull: nothing in the header
