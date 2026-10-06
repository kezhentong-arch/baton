"""Three data sets behind URL prefixes: the example is read-only, practice resets, only the main board pulls team goals.
Plus the pages in both languages."""
import json
import re
import threading
import urllib.error
import urllib.request

import pytest

from app import settings
from app.seed import seed_demo
from app.store import db_path, open_db, set_meta
from app.model import utc_now
from tests.conftest import make_config

CJK = re.compile(r"[一-鿿]")


def _req(port, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, method="POST" if data is not None else "GET",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


@pytest.fixture
def serve():
    servers = []

    def _serve(cfg):
        from app.sample import build_practice
        from app.server import make_server
        settings.use(cfg)
        conn = open_db(db_path(False))
        with conn:
            set_meta(conn, "person", cfg["person"]["id"])
        conn.close()
        build_practice()
        srv = make_server(cfg, 0)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        servers.append(srv)
        return srv.server_address[1]
    yield _serve
    for srv in servers:
        srv.shutdown()


def test_modes(serve):
    port = serve(make_config())
    for path in ("/", "/sample/", "/practice/", "/sample/goal/E1", "/guide", "/practice/guide"):
        assert _req(port, path)[0] == 200, path
    code, body = _req(port, "/sample/api/act", {"action": "todo_add", "params": {"text": "x"}})
    assert code == 403 and "只读" in body.decode()
    code, body = _req(port, "/practice/api/act", {"action": "todo_add", "params": {"text": "练手"}})
    assert code == 200 and json.loads(body)["ok"]
    code, _ = _req(port, "/practice/api/reset", {})
    assert code == 200
    s = json.loads(_req(port, "/practice/api/state")[1])
    assert all(todo["text"] != "练手" for todo in s["todos"])  # the practice change is gone after the reset
    assert _req(port, "/sample/api/pull", {})[0] == 403
    assert _req(port, "/api/act", {"action": "log", "params": {"goal": "C1", "text": "x", "_sync": "pushed"}})[0] == 400
    # the example = a live mirror of the main board + hypothetical cases: a goal created on the main page is on the
    # example page at once, and the hypothetical cases are still there
    code, body = _req(port, "/api/act", {"action": "goal_create", "params": {"title": "镜像核对", "line": "个人事项"}})
    assert code == 200 and json.loads(body)["ok"], body
    titles = {g["title"] for ln in json.loads(_req(port, "/sample/api/state")[1])["lines"] for g in ln["goals"]}
    assert "镜像核对" in titles and "宠物寄养预约（假设案例）" in titles, titles
    real_titles = {g["title"] for ln in json.loads(_req(port, "/api/state")[1])["lines"] for g in ln["goals"]}
    assert "宠物寄养预约（假设案例）" not in real_titles  # hypothetical cases stay on the example board
    assert not list(settings.data_dir().glob("sample*"))  # the example is never written to a file
    assert json.loads(_req(port, "/healthz")[1])["service"] == "personal-board"


def test_binds_loopback_only(serve):
    from app.server import make_server
    srv = make_server(make_config(), 0)
    try:
        assert srv.server_address[0] == "127.0.0.1"
    finally:
        srv.server_close()


@pytest.mark.parametrize("lang", ["zh", "en"])
def test_pages_follow_the_configured_language(serve, lang):
    """Home, goal detail and guide pages in each language: the <html lang> follows, no unrendered placeholder is left,
    and with the English config and English demo data no Chinese text reaches the page."""
    cfg = make_config(lang)
    settings.use(cfg)
    conn = open_db(db_path(False))
    seed_demo(conn, lang, utc_now())
    conn.close()
    port = serve(cfg)
    want = {"zh": '<html lang="zh-CN"', "en": '<html lang="en"'}[lang]
    for path in ("/", "/goal/G2", "/goal/G6.3", "/guide", "/sample/", "/practice/goal/E1.2"):
        code, body = _req(port, path)
        html = body.decode()
        assert code == 200 and want in html, path
        assert "{{" not in html.split("window.__I18N__")[0], path          # every template placeholder was rendered
        if lang == "en":
            assert not CJK.search(html), (path, CJK.findall(html)[:20])
    state = json.loads(_req(port, "/api/state")[1])
    names = [ln["name"] for ln in state["lines"]]
    assert names == (["产品", "增长", "运营", "团队协作", "个人事项"] if lang == "zh" else ["Product", "Growth", "Operations", "Team", "Personal"])
    api = _req(port, "/api/actions")[1].decode() + _req(port, "/api/timeline?from=2020-01-01T00:00:00Z&to=2030-01-01T00:00:00Z")[1].decode() \
        + _req(port, "/api/pending")[1].decode() + json.dumps(state, ensure_ascii=False)
    if lang == "en":
        assert not CJK.search(api), CJK.findall(api)[:20]
    else:
        assert "立项" in api and "Created" not in api


def test_no_team_board_means_no_pull_and_no_noise(serve):
    """Without team_board.base_url the board is standalone: nothing is marked unpushed, the header says nothing about
    the team board, and the pull endpoint refuses instead of reporting a connection error."""
    cfg = make_config(team_board={"base_url": "", "token": ""})
    port = serve(cfg)
    code, body = _req(port, "/api/act", {"action": "goal_create", "params": {"title": "独立使用", "line": "产品"}})
    assert code == 200
    gnum = json.loads(body)["gnum"]
    assert _req(port, "/api/act", {"action": "stage_start", "params": {"goal": gnum, "stage": "开发"}})[0] == 200
    h = json.loads(_req(port, "/api/state")[1])["header"]
    assert h["team_board"] is False and h["pending_count"] == 0 and h["team_pulled"] == "" and h["team_pull_error"] == ""
    assert json.loads(_req(port, "/api/pending")[1])["entries"] == []
    code, body = _req(port, "/api/pull", {})
    assert code == 409 and "没有连团队看板" in json.loads(body)["error"]
    conn = open_db(db_path(False))
    assert conn.execute("SELECT COUNT(*) FROM entries WHERE sync IS NOT NULL").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM meta WHERE key LIKE 'team_%'").fetchone()[0] == 0   # no pull was ever attempted
