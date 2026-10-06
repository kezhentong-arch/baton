"""中英双语：翻译表两套都完整；lang=en 时页面、报错、接口说明里不夹中文；<html lang> 与品牌字样跟配置走。"""
import re
from pathlib import Path

import pytest

from team_board import config, i18n
from tests.conftest import client_as, raw_cfg

CJK = re.compile(r"[一-鿿]")
ROOT = Path(__file__).resolve().parents[1] / "team_board"

EN = {
    "title": "Team Board", "lang": "en",
    "timezone": {"name": "America/New_York", "label": "New York"}, "second_timezone": None,
    "people": [
        {"id": "alex", "name": "Alex", "letter": "A", "role": "owner", "token": "tok-alex-0001"},
        {"id": "ben", "name": "Ben", "letter": "B", "role": "member", "token": "tok-ben-0002"},
        {"id": "chloe", "name": "Chloe", "letter": "C", "role": "member", "token": "tok-chloe-0003"},
    ],
    "lines": ["Product", "Growth", "Operations", "Team"],
    "stages": ["Business", "Product", "Design", "Dev", "Test"],
    "github": {"enabled": True, "repos": [{"repo": "acme/app", "line": "Product"}],
               "label_map": [{"pattern": "stage: dev", "state": "Dev"}], "delivered": ["Done"]},
}


def _placeholders(s: str) -> set[str]:
    return set(re.findall(r"(?<!\{)\{(\w+)\}(?!\})", s))


def test_every_key_has_both_languages_with_matching_placeholders():
    odd = {"jump.month"}                 # 中文用年、月的数字，英文用月份名：占位符本来就不同
    for key, pair in i18n.M.items():
        assert len(pair) == 2 and all(isinstance(x, str) for x in pair), key
        zh, en = pair
        assert zh.strip() or key == "when.now", key
        assert not CJK.search(en), f"英文那一列夹了中文：{key}"
        if key not in odd:
            assert _placeholders(zh) == _placeholders(en), key
    assert i18n.html_lang("zh") == "zh-CN" and i18n.html_lang("en") == "en"


def test_every_key_used_in_code_and_templates_exists():
    used: set[str] = set()
    for path in [*ROOT.rglob("*.py"), *ROOT.rglob("*.html")]:
        text = path.read_text(encoding="utf-8")
        used |= set(re.findall(r"""\b(?:t|tr|_fail|_blocker)\(\s*(?:[\w.]+,\s*)?["']([a-z]+[a-z0-9_]*(?:\.[a-zA-Z0-9_]+)+)["']""", text))
        used |= set(re.findall(r"""T\["([a-z]+\.[a-z_]+)"\]""", text))
    used = {k.replace("blk.late", "blk.late") for k in used}
    missing = sorted(k for k in used if k not in i18n.M and not k.endswith(".py") and not k.endswith(".md"))
    assert not missing, missing
    for name in ("late", "dragged", "dep", "pause", "stale", "subcontract", "version"):
        assert f"blk.{name}" in i18n.M
    from team_board.board.actions import _FIELDS
    for action in _FIELDS:
        assert f"act.{action}.desc" in i18n.M and f"act.{action}.who" in i18n.M, action
    assert len(used) > 300                       # 扫描本身没失效


def test_no_user_facing_chinese_literals_left_in_python_code():
    """界面文字都该在翻译表里：除 i18n.py、示例数据 seed.py 和初始配置里的示例团队外，代码的字符串里不该有中文（注释和文档串不算）。"""
    import ast
    offenders = []
    for path in ROOT.rglob("*.py"):
        if path.name in ("i18n.py", "seed.py"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docs = {id(n.body[0].value) for n in ast.walk(tree)
                if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                and n.body and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs and CJK.search(node.value):
                if path.name == "config.py" and node.value in ("林夏", "周行", "苏禾", "产品", "增长", "运营", "团队协作", "业务", "开发", "测试"):
                    continue
                offenders.append((path.name, node.lineno, node.value[:30]))
    assert not offenders, offenders


def test_templates_have_no_hardcoded_chinese_outside_comments():
    for path in ROOT.rglob("*.html"):
        text = re.sub(r"\{#.*?#\}", "", path.read_text(encoding="utf-8"), flags=re.S)      # 模板注释不会发到浏览器
        assert not CJK.search(text), (path.name, CJK.search(text).group(0), text[max(0, CJK.search(text).start() - 60):CJK.search(text).start() + 20])


@pytest.fixture
def en(tmp_path):
    app, c = client_as(tmp_path, "alex", **EN)
    return app, c


def _act(c, action, **params):
    r = c.post("/api/board/act", json={"action": action, "params": params})
    assert r.status_code == 200, r.text
    return r.json()


def _fill(app, c):
    """一块内容尽量全的看板：环节、暂停、依赖冲突、延期、改期、完成、放弃、跨线、口述、版本、来源号。"""
    from team_board.board.store import connect_board
    conn = connect_board(app.state.cfg.data_dir)
    conn.execute("INSERT INTO gh_milestones(repo, number, title, state, due_on, created_at, closed_at) VALUES(?,?,?,?,?,?,?)",
                 ("acme/app", 3, "v2.0", "OPEN", None, "2026-09-01T00:00:00+00:00", None))
    conn.commit()
    conn.close()
    top = _act(c, "create", title="Launch paid membership", line="Product", owner="alex", due="2020-01-05",
               note="See https://docs.example.com/spec for the plan.", occurred_at="2020-01-01T10:00:00-05:00")["goal_id"]
    a = _act(c, "create", title="Payments backend", owner="ben", parent_id=top, due="2099-03-01", version="acme/app#3")["goal_id"]
    b = _act(c, "create", title="Membership screens", owner="chloe", parent_id=top, due="2099-02-01", source="A7")["goal_id"]
    ops = _act(c, "create", title="Admin pricing", owner="chloe", parent_id=top, line="Operations", version="acme/app#3")["goal_id"]
    _act(c, "declare_dependency", goal_id=b, on_goal=a, at_stage="Dev", need_by="2099-01-15")
    _act(c, "start_stage", goal_id=b, stage="Product")
    _act(c, "start_stage", goal_id=b, stage="Design", executor="alex")
    _act(c, "pause", goal_id=b, kind="dependency", depends_on=a, note="needs the API")
    _act(c, "start_stage", goal_id=a, stage="Dev")
    _act(c, "change_due", goal_id=a, due="2099-03-05 08:00", reason="provider review is slow")
    done = _act(c, "create", title="Landing page", line="Growth", owner="alex")["goal_id"]
    _act(c, "complete", goal_id=done, done_what="Landing page is live")
    gone = _act(c, "create", title="Old idea", line="Growth", owner="alex")["goal_id"]
    _act(c, "abandon", goal_id=gone, reason="not worth it")
    _act(c, "create", title="Crash rate", line="Product", owner="ben", long_term="1")
    _act(c, "create", title="A sample case", line="Team", owner="alex", sample="1", due="2020-02-02")
    _act(c, "track_version", ref="acme/app#3")
    note = _act(c, "add_note", text="Testing found 5 issues today", goal_id=b)["event_ids"][0]
    _act(c, "add_note", text="Next up: pet weight log")
    _act(c, "resolve_note", note_id=note, summary="Recorded the test start")
    _act(c, "link_weekly", week_start="2026-09-28", url="https://docs.example.com/weekly")
    return {"top": top, "a": a, "b": b, "ops": ops, "done": done, "gone": gone}


def test_english_pages_have_no_chinese_left(en):
    app, c = en
    ids = _fill(app, c)
    pages = ["/board", "/board?zoom=day", "/board?person=ben", "/board?line=Product&active=1", "/board?zoom=nope&person=x&line=y",
             "/board/practice", "/board/sample", "/board/version?repo=acme/app&number=3",
             *(f"/board/goal/{i}" for i in ids.values()), f"/board/practice/goal/{ids['b']}"]
    for url in pages:
        r = c.get(url)
        assert r.status_code == 200, url
        hit = CJK.search(r.text)
        assert not hit, (url, r.text[max(0, hit.start() - 80):hit.start() + 20])
        assert '<html lang="en">' in r.text, url
    index = c.get("/board").text
    assert "<title>Team Board</title>" in index and "What&#39;s happening now" in index and "Dictation" in index
    assert "Dependency at risk" in index and "Paused" in index and "Late" in index and "(New York)" in index
    assert "Please record the dictation below on the team board (dictation #{id})" in index
    assert "on the PRACTICE board" in c.get("/board/practice").text
    goal = c.get(f"/board/goal/{ids['b']}").text
    assert "Source A7" in goal and "Waiting on a dependency" in goal and "Edit by hand" in goal and "History (" in goal
    assert "Created: Membership screens (Product), source A7" in goal
    top = c.get(f"/board/goal/{ids['top']}").text
    assert 'href="https://docs.example.com/spec"' in top and "overdue" in top and "Sub-goals" in top
    sample = c.get("/board/sample").text
    assert 'class="bd-sampletag">Sample' in sample and "A sample case" in sample and "A sample case" not in index


def test_english_errors_action_reference_and_state(en):
    app, c = en
    ids = _fill(app, c)
    spec = c.get("/api/board/actions").json()
    assert not CJK.search(str(spec)) and spec["lang"] == "en" and spec["title"] == "Team Board"
    assert spec["values"]["stage"] == ["Business", "Product", "Design", "Dev", "Test"]
    assert spec["values"]["pause_kind"] == {"dependency": "Waiting on a dependency", "external": "Waiting on someone outside"}
    assert spec["timezone"] == {"name": "America/New_York", "label": "New York"} and spec["second_timezone"] is None
    assert "Team owners" in spec["actions"]["assign"]["who"]
    state = c.get("/api/board/state").json()
    assert not CJK.search(str(state))
    g = next(x for x in state["goals"] if x["id"] == ids["b"])
    assert g["status"] == "In progress" and g["status_key"] == "active" and g["owner"] == "Chloe" and g["owner_key"] == "chloe"
    assert g["paused"] == "Waiting on a dependency" and g["paused_kind"] == "dependency" and g["source"] == "A7"
    for action, params, hint in [
        ("start_stage", {"goal_id": ids["a"], "stage": "Dev"}, "“Dev” is already in progress"),
        ("start_stage", {"goal_id": ids["a"], "stage": "Shipping"}, "stage must be one of: Business, Product, Design, Dev, Test"),
        ("complete", {"goal_id": ids["top"]}, "Some sub-goals are still open"),
        ("create", {"title": "x", "owner": "alex"}, "Missing line"),
        ("create", {"title": "x", "owner": "alex", "line": "Team", "source": "Z9"}, "letter + a sequence"),
        ("change_due", {"goal_id": ids["a"], "due": "soon", "reason": "x"}, "must look like 2026-10-15"),
        ("nope", {}, "No such action: nope"),
    ]:
        r = c.post("/api/board/act", json={"action": action, "params": params})
        assert r.status_code >= 400 and hint in r.json()["error"] and not CJK.search(r.json()["error"]), (action, r.text)
    _app2, ben = client_as(app.state.cfg.data_dir.parent, "ben", **EN)
    denied = ben.post("/api/board/act", json={"action": "abandon", "params": {"goal_id": ids["a"], "reason": "x"}})
    assert denied.status_code == 403 and denied.json()["error"].startswith("Only a team owner can do this")


def test_durations_and_lateness_read_naturally_in_english(tmp_path):
    from datetime import datetime, timedelta
    from team_board.board.model import duration_text, late_text, tz
    config.use(config.parse_config(raw_cfg(tmp_path, **EN)))
    assert [duration_text(timedelta(seconds=s)) for s in (10, 720, 3600, 4800, 86400, 129600)] == [
        "under 1 min", "12 min", "1 hour", "1.3 hours", "1 day", "1.5 days"]
    t0 = datetime(2026, 10, 1, 8, 0, tzinfo=tz())
    assert [late_text(t0, t0 + d) for d in (timedelta(minutes=59), timedelta(hours=1), timedelta(hours=3, minutes=29),
                                             timedelta(hours=30), timedelta(days=12))] == ["", "1 hour", "3 hours", "1.3 days", "12 days"]


def test_title_and_single_timezone_follow_config(tmp_path):
    """品牌字样是配置项 title；没配第二时区时页面和接口只写一地。"""
    _app, c = client_as(tmp_path, title="爪印进度", second_timezone=None,
                        timezone={"name": "Asia/Tokyo", "label": "东京"})
    c.post("/api/board/act", json={"action": "create", "params": {
        "title": "会员订阅上线", "line": "客户端", "owner": "linxia", "due": "2099-01-01 08:00"}})
    page = c.get("/board").text
    assert "<title>爪印进度</title>" in page and "<b>爪印进度</b>" in page and "<h2>爪印进度</h2>" in page
    goal = c.get("/board/goal/1").text
    assert "（东京）" in goal and "洛杉矶" not in goal and "上海" not in goal
    spec = c.get("/api/board/actions").json()
    assert spec["timezone"]["label"] == "东京" and spec["second_timezone"] is None
    g = c.get("/api/board/state").json()["goals"][0]
    assert g["latest_due"] == "2099-01-01 08:00"            # 截止时刻按主时区（东京）算
    from team_board.board.model import Due
    config.use(_app.state.cfg)
    assert Due.parse("2099-01-01 08:00").at.utcoffset().total_seconds() == 9 * 3600
    default = config.parse_config(config.starter_config("zh", data_dir=str(tmp_path / "x")))
    assert default.title == "团队看板" and config.parse_config(config.starter_config("en", data_dir=str(tmp_path / "x"))).title == "Team Board"


def test_lines_and_stages_are_whatever_the_config_says(tmp_path):
    """线、环节的名字和个数都来自配置：换一套完全不同的也照常工作，颜色、序号跟着走。"""
    _app, c = client_as(tmp_path, lines=[{"name": "硬件", "color": "#112233"}, "软件"], stages=["调研", "打样", "量产"],
                        github={"enabled": False})
    assert c.get("/api/board/actions").json()["values"]["line"] == ["硬件", "软件"]
    gid = c.post("/api/board/act", json={"action": "create", "params": {"title": "新外壳", "line": "硬件", "owner": "linxia"}}).json()["goal_id"]
    assert c.post("/api/board/act", json={"action": "start_stage", "params": {"goal_id": gid, "stage": "量产"}}).status_code == 200
    bad = c.post("/api/board/act", json={"action": "start_stage", "params": {"goal_id": gid, "stage": "开发"}})
    assert bad.status_code == 400 and "调研、打样、量产" in bad.json()["error"]
    page = c.get("/board").text
    assert "--lc:#112233" in page and '<span class="bd-lnum">①</span>硬件' in page and '<span class="bd-lnum">②</span>软件' in page
    assert "--st2:" in page and "--st3:" not in page and "border-color:var(--st2)" in page
    assert "立即同步" not in page and "GitHub 数据" not in page            # 没开 GitHub 同步：页头不出现同步那一套
    state = c.get("/api/board/state").json()
    assert state["goals"][0]["stage_days"].keys() == {"调研", "打样", "量产"} and state["sync"]["enabled"] is False
