"""Configuration drives everything: who, lines (and which one is personal), stages, time zones, the team board."""
import json
from datetime import datetime, timedelta, timezone
from unittest import mock

import pytest

import app.team as team
from app import settings
from app.actions import ActionError, apply_action, open_stages, values
from app.store import get_meta, open_db
from app.view import goal_detail, state, timeline
from tests.conftest import make_config

NOW = datetime(2026, 10, 2, 16, 0, tzinfo=timezone.utc)

STUDIO = {
    "lang": "en", "person": {"id": "sam", "name": "Sam", "letter": "S"}, "port": 21555,
    "timezone": "Europe/Berlin",
    "lines": [{"name": "Clients", "color": "#123456"}, {"name": "Studio"}, {"name": "Errands", "personal": True},
              {"name": "Garden", "personal": True}],
    "stages": ["Sketch", {"name": "Build", "color": "#abcdef"}, "Ship"],
    "team_board": {"base_url": "https://team.example.test/", "token": "t0ken"},
}


def _db(tmp_path, name="t.sqlite", person="sam"):
    c = open_db(tmp_path / name)
    with c:
        c.execute("INSERT INTO meta(key, value) VALUES('person', ?)", (person,))
    return c


def test_custom_people_lines_stages_and_zone(tmp_path):
    cfg = settings.use(STUDIO)
    assert cfg["timezone"] == {"name": "Europe/Berlin", "label": "Berlin"} and "second_timezone" not in cfg
    assert settings.team_line_names() == ["Clients", "Studio"] and cfg["team_board"]["base_url"] == "https://team.example.test"
    assert values()["line"] == ["Clients", "Studio", "Errands", "Garden"] and values()["stage"] == ["Sketch", "Build", "Ship"]
    conn = _db(tmp_path)
    a = apply_action(conn, "goal_create", {"title": "Logo", "line": "Clients", "due": "2026-10-09"}, NOW)
    b = apply_action(conn, "goal_create", {"title": "Dentist", "line": "Errands"}, NOW)
    c = apply_action(conn, "goal_create", {"title": "Tomatoes", "line": "Garden"}, NOW)
    assert (a.gnum, b.gnum, c.gnum) == ("S1", "S2", "S3")
    apply_action(conn, "stage_start", {"goal": "S1", "stage": "Build"}, NOW)
    for old_name in ("开发", "Dev", "build"):
        with pytest.raises(ActionError, match="stage must be one of Sketch, Build, Ship"):
            apply_action(conn, "stage_start", {"goal": "S1", "stage": old_name}, NOW)
    with pytest.raises(ActionError, match="line must be one of"):
        apply_action(conn, "goal_create", {"title": "x", "line": "个人事项"}, NOW)
    # only goals on lines without the personal flag are ever marked for the team board — whatever the lines are called
    sync = {r["title"]: r["sync"] for r in conn.execute("SELECT g.title, e.sync FROM entries e JOIN goals g ON g.id=e.goal_id WHERE e.kind='goal_create'")}
    assert sync == {"Logo": "pending", "Dentist": None, "Tomatoes": None}
    s = state(conn, NOW.astimezone(settings.tz()).date(), NOW)
    assert [(ln["mark"], ln["name"], ln["personal"]) for ln in s["lines"]] == [("①", "Clients", False), ("②", "Studio", False), ("③", "Errands", True), ("④", "Garden", True)]
    assert s["lines"][0]["color"] == "#123456" and s["stage_colors"]["Build"] == "#abcdef"
    assert s["header"]["clock"] == "Berlin 10-02 18:00" and s["header"]["person_name"] == "Sam"
    assert s["hours"][0]["hour"] == "18"                                   # entries are grouped by the hour of the configured zone
    assert s["day"]["label"] == "Fri 10-02"
    row = next(r for r in timeline(conn, NOW - timedelta(days=1), NOW + timedelta(days=1), NOW)["rows"] if r["gnum"] == "S1")
    assert row["spans"][0]["color"] == "#abcdef"
    # moving a goal from a personal line to a team line queues its creation for the push; the reverse direction does not
    apply_action(conn, "goal_update", {"goal": "S2", "line": "Studio"}, NOW)
    assert conn.execute("SELECT sync FROM entries WHERE goal_id=? AND kind='goal_create'", (b.goal_id,)).fetchone()[0] == "pending"


def test_config_validation():
    for bad in ({**STUDIO, "lang": "fr"}, {**STUDIO, "timezone": "Mars/Olympus"}, {**STUDIO, "lines": []},
                {**STUDIO, "stages": ["A", "A"]}, {**STUDIO, "person": {"id": "", "letter": "S"}},
                {**STUDIO, "person": {"id": "sam", "letter": "G"}}, {**STUDIO, "team_board": {"base_url": "ftp://x"}}):
        with pytest.raises(settings.ConfigError):
            settings.normalize(bad)
    cfg = settings.normalize({"person": {"id": "me", "letter": "M"}})      # everything else has a default
    assert cfg["lang"] == "en" and cfg["port"] == 10990 and cfg["timezone"]["name"] == "America/Los_Angeles"
    assert [ln["name"] for ln in cfg["lines"] if ln["personal"]] == ["Personal"] and len(cfg["stages"]) == 5
    assert cfg["team_board"]["base_url"] == "" and "second_timezone" not in cfg
    assert settings.default_config("zh")["lines"][-1] == {"name": "个人事项", "color": settings.PERSONAL_COLOR, "personal": True}
    assert settings.default_letter("Grace") == "P" and settings.default_letter("alex") == "A"


def test_defaults_never_point_at_a_shared_place(monkeypatch):
    monkeypatch.delenv(settings.ENV_DATA)
    assert settings.data_dir().name == "personal-board" and settings.DEFAULT_PORT == 10990
    example = json.loads((settings.Path(__file__).resolve().parents[1] / "config.example.json").read_text(encoding="utf-8"))
    cfg = settings.normalize(example)                                      # the example file is a valid config
    assert cfg["team_board"]["token"] == "" and cfg["team_board"]["base_url"] == ""


def test_without_team_board_nothing_is_marked_and_nothing_is_pulled(tmp_path):
    settings.use(make_config(team_board={"base_url": "", "token": ""}))
    conn = _db(tmp_path, person="linxia")
    g = apply_action(conn, "goal_create", {"title": "单独用", "line": "产品", "due": "2026-10-05"}, NOW)
    apply_action(conn, "stage_start", {"goal": g.gnum, "stage": "开发"}, NOW)
    apply_action(conn, "goal_update", {"goal": g.gnum, "due": "2026-10-06", "what": "改一下"}, NOW)
    apply_action(conn, "complete", {"goal": g.gnum, "done_what": "做完了"}, NOW)
    p = apply_action(conn, "goal_create", {"title": "每月的事", "line": "运营", "point_at": "2026-11-01 10:00", "repeat": "monthly"}, NOW)
    assert conn.execute("SELECT COUNT(*) FROM entries WHERE sync IS NOT NULL").fetchone()[0] == 0
    h = state(conn, NOW.date(), NOW)["header"]
    assert (h["team_board"], h["pending_count"], h["team_pulled"], h["team_pull_error"]) == (False, 0, "", "")
    assert goal_detail(conn, g.gnum, NOW)["goal"]["pending"] == 0 and p.gnum
    with mock.patch.object(team, "fetch_state") as fetch:
        r = team.pull(conn, NOW)
    assert r["ok"] is False and not fetch.called
    assert get_meta(conn, "team_pull_error") is None and get_meta(conn, "team_pulled_at") is None   # switched off leaves no trace


def test_team_request_uses_bearer_token_and_configured_address(monkeypatch):
    settings.use(STUDIO)
    seen = {}

    class Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b'{"goals": []}'

    def fake_urlopen(req, timeout=0):
        seen["url"], seen["headers"] = req.full_url, {k.lower(): v for k, v in req.header_items()}
        return Resp()
    monkeypatch.setattr(team.urllib.request, "urlopen", fake_urlopen)
    tb = settings.team_board()
    assert team.fetch_state(tb["base_url"], tb["token"]) == {"goals": []}
    assert seen["url"] == "https://team.example.test/api/board/state"
    assert seen["headers"]["authorization"] == "Bearer t0ken" and seen["headers"]["user-agent"].startswith("personal-board/")
    assert set(seen["headers"]) == {"authorization", "user-agent", "accept"}          # nothing else identifies the caller
    monkeypatch.setenv(settings.ENV_TEAM_TOKEN, "from-env")                           # the environment overrides the file
    assert settings.team_board()["token"] == "from-env"
    team.fetch_state("http://127.0.0.1:9", "")
    assert "authorization" not in seen["headers"]                                     # no token, no header
    with pytest.raises(RuntimeError):
        team.fetch_state("ftp://nope")


def test_pull_matches_owner_and_maps_names_from_config(tmp_path):
    """The team board answers in its own words: English status labels or keys, the owner's display name or id, and line /
    stage names that `team_name` maps onto the local ones."""
    cfg = dict(STUDIO, lines=[{"name": "Clients", "team_name": "Client work"}, {"name": "Studio"}, {"name": "Errands", "personal": True}],
               stages=["Sketch", {"name": "Build", "team_name": "Dev"}, "Ship"])
    settings.use(cfg)
    conn = _db(tmp_path)
    base = {"parent_id": None, "sample": False, "long_term": False, "baseline_due": "", "latest_due": ""}
    payload = {"goals": [
        dict(base, id=1, gnum="G1", title="Rebrand", line="Client work", status="In progress", owner="Sam",
             current_stages=["Dev"], spans=[{"stage": "Dev", "start": "2026-10-01T08:00:00+00:00", "end": ""}], paused="waiting on the client"),
        dict(base, id=2, gnum="G2", title="By id", line="Studio", status="done", owner="Somebody", owner_id="sam", done_at="2026-10-01T09:00:00+00:00"),
        dict(base, id=3, gnum="G3", title="Dropped", line="Studio", status="Abandoned", owner="sam", abandoned_at="2026-10-01T10:00:00+00:00",
             abandon_reason="merged into G1"),
        dict(base, id=4, gnum="G4", title="Not mine", line="Studio", status="In progress", owner="Ben"),
        dict(base, id=5, gnum="G5", title="Unknown line", line="Elsewhere", status="In progress", owner="Sam"),
    ]}
    with mock.patch.object(team, "fetch_state", return_value=payload):
        r = team.pull(conn, NOW)
    assert r == {"ok": True, "pulled": 3, "error": ""}
    rows = {g["gnum"]: g for g in conn.execute("SELECT * FROM goals")}
    assert set(rows) == {"G1", "G2", "G3"}
    assert rows["G1"]["line"] == "Clients" and rows["G1"]["owner"] == "sam" and rows["G1"]["blocker"] == "Paused: waiting on the client"
    assert list(open_stages(conn, rows["G1"]["id"])) == ["Build"]
    assert rows["G2"]["status"] == "done" and rows["G3"]["status"] == "abandoned"
    assert goal_detail(conn, "G3", NOW)["abandon_reason"] == "merged into G1"
    kinds = [r["text"] for r in conn.execute("SELECT text FROM entries WHERE goal_id=? ORDER BY id", (rows["G2"]["id"],))]
    assert kinds == ["Created (on the team board; backfilled by the pull — the team board has the exact time)", "Marked Done on the team board"]
    row = next(x for x in timeline(conn, NOW - timedelta(days=3), NOW, NOW)["rows"] if x["gnum"] == "G1")
    assert row["blocker_short"] == "waiting on the client"
    # switching the interface language later still recognises what the pull wrote
    settings.use(dict(cfg, lang="zh"))
    assert goal_detail(conn, "G3", NOW)["abandon_reason"] == "merged into G1"
    assert next(x for x in timeline(conn, NOW - timedelta(days=3), NOW, NOW)["rows"] if x["gnum"] == "G1")["blocker_short"] == "waiting on the client"
