"""看板 MCP（team_board/mcp.py）：协议骨架、参数严格、报错原样带回、口述查找与时间换算、手册按语言下发。

看板本身的规则在 test_board_actions.py 里测；这里只测薄包装不会吞错、不会猜。
HTTP 用假 Board 顶掉，不起站。
"""
import json

import pytest

from team_board import i18n, mcp

LA = {"name": "America/Los_Angeles", "label": "洛杉矶"}
SH = {"name": "Asia/Shanghai", "label": "上海"}


class FakeBoard:
    local = True
    base = "http://127.0.0.1:0"

    def __init__(self, state=None, me="zhouxing"):
        self.calls = []
        self.state_calls = []           # 每次读现状读的是正式（False）还是练手（True）
        self.me = me
        self._state = state or {"goals": [{"id": 5}], "notes": [{"id": 9, "who": "周行", "who_key": "zhouxing", "goal_id": 5}]}

    def actions(self):
        return {"actions": {"create": {"required": ["title", "owner"]}}, "values": {"people": {}},
                "timezone": LA, "second_timezone": SH, "lang": "zh"}

    meta = actions

    def state(self, practice=False):
        self.state_calls.append(practice)
        return self._state

    def act(self, action, params, practice=False):
        self.calls.append((action, params, practice))
        if action == "create" and self.me != "linxia":
            raise mcp.BoardError("看板拒绝（HTTP 403）：这个操作只有团队负责人能做")
        return {"ok": True, "event_ids": [1], "goal_id": 7}


def _rpc(board, method, params=None, rid=1):
    return mcp.handle(board, "手册正文", {"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})


def test_initialize_lists_tools_and_carries_manual():
    b = FakeBoard()
    init = _rpc(b, "initialize", {"protocolVersion": "2025-03-26"})["result"]
    assert init["protocolVersion"] == "2025-03-26" and init["instructions"] == "手册正文"
    assert init["serverInfo"]["name"] == "team-board"
    names = {t["name"] for t in _rpc(b, "tools/list")["result"]["tools"]}
    assert names == {"board_actions", "board_guide", "board_state", "board_note", "board_time", "board_act",
                     "board_resolve_note"}
    assert mcp.handle(b, "", {"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    assert _rpc(b, "nope")["error"]["code"] == -32601


def test_act_passes_through_and_server_rejection_is_error_not_success():
    b = FakeBoard()
    ok = _rpc(b, "tools/call", {"name": "board_act", "arguments": {
        "action": "start_stage", "params": {"goal_id": 5, "stage": "测试"}}})["result"]
    assert ok["isError"] is False and b.calls == [("start_stage", {"goal_id": 5, "stage": "测试"}, False)]
    denied = _rpc(b, "tools/call", {"name": "board_act", "arguments": {
        "action": "create", "params": {"title": "x", "owner": "zhouxing"}}})["result"]
    assert denied["isError"] is True and "只有团队负责人" in denied["content"][0]["text"]


def test_identity_cannot_be_self_reported_any_more():
    """身份只由连接用的个人令牌决定：工具不再有「以谁的身份」这个参数，传了当成不认识的参数拒绝。"""
    b = FakeBoard()
    for tool in mcp.tools():
        assert "as_person" not in tool["inputSchema"]["properties"]
    r = _rpc(b, "tools/call", {"name": "board_act", "arguments": {
        "action": "void", "params": {}, "as_person": "linxia"}})["result"]
    assert r["isError"] is True and "不认识的参数" in r["content"][0]["text"] and b.calls == []
    board = mcp.Board("http://127.0.0.1:1", "tok-zhouxing")
    assert board._headers()["Authorization"] == "Bearer tok-zhouxing"
    assert "Authorization" not in mcp.Board("http://127.0.0.1:1")._headers()       # 本地试用模式可以不带令牌
    with pytest.raises(mcp.BoardError):                                           # 令牌不走明文 http 出本机
        mcp.Board("http://board.example.com", "tok")


@pytest.mark.parametrize("args, hint", [
    ({"action": "void"}, "缺少参数：params"),
    ({"action": "void", "params": {}, "dry": True}, "不认识的参数"),
    ({"action": "void", "params": "x"}, "类型不对"),
])
def test_bad_arguments_fail_before_any_write(args, hint):
    b = FakeBoard()
    r = _rpc(b, "tools/call", {"name": "board_act", "arguments": args})["result"]
    assert r["isError"] is True and hint in r["content"][0]["text"] and b.calls == []


def test_note_lookup_and_missing_notes_field_is_explicit():
    b = FakeBoard()
    found = _rpc(b, "tools/call", {"name": "board_note", "arguments": {"note_id": 9}})["result"]
    assert found["isError"] is False and '"who": "周行"' in found["content"][0]["text"]
    missing = _rpc(b, "tools/call", {"name": "board_note", "arguments": {"note_id": 10}})["result"]
    assert missing["isError"] is True and "不存在" in missing["content"][0]["text"]
    no_field = _rpc(FakeBoard({"goals": []}), "tools/call", {"name": "board_note", "arguments": {"note_id": 9}})["result"]
    assert no_field["isError"] is True and "notes 字段" in no_field["content"][0]["text"]


def test_resolve_note_is_a_board_action():
    b = FakeBoard()
    _rpc(b, "tools/call", {"name": "board_resolve_note", "arguments": {"note_id": 9, "summary": "录了测试开始"}})
    assert b.calls == [("resolve_note", {"note_id": 9, "summary": "录了测试开始"}, False)]


def test_time_conversion_uses_zoneinfo_and_writes_both_zones_when_configured():
    r = mcp.board_time("2026-09-29 14:30", "primary", LA, SH)
    assert r["both"] == "09-29 14:30（洛杉矶）= 09-30 05:30（上海）"
    assert r["occurred_at"] == "2026-09-29T14:30:00-07:00"
    r2 = mcp.board_time("2026-12-01 09:00", "second", LA, SH)       # 冬令时偏移不同，不能写死 -7
    assert r2["occurred_at"] == "2026-11-30T17:00:00-08:00"
    assert mcp.board_time("2026-09-29T14:30:00+08:00", "primary", LA, SH)["primary"].startswith("2026-09-28 23:30")
    with pytest.raises(mcp.BoardError):
        mcp.board_time("昨天下午", "primary", LA, SH)
    now = mcp.board_time(None, "primary", LA, SH)
    assert "洛杉矶" in now["primary"] and "上海" in now["second"]


def test_time_conversion_writes_one_zone_when_no_second_zone():
    """没配第二时区：所有「两地都写」的地方只写一地。"""
    r = mcp.board_time("2026-09-29 14:30", "primary", LA, None)
    assert r["both"] == "09-29 14:30（洛杉矶）" and "second" not in r
    with pytest.raises(mcp.BoardError, match="第二时区"):
        mcp.board_time("2026-09-29 14:30", "second", LA, None)
    via_tool = _rpc(FakeBoard(), "tools/call", {"name": "board_time", "arguments": {"when": "2026-09-29 14:30"}})["result"]
    assert via_tool["isError"] is False and "上海" in via_tool["content"][0]["text"]     # 假看板配了第二时区


# ---- 手册全文：有的客户端只显示 instructions 的前两千字左右，录入流程靠 board_guide 读全 ----

def _guide(board=None):
    return _rpc(board or FakeBoard(), "tools/call", {"name": "board_guide", "arguments": {}})["result"]


def test_guide_returns_the_full_bundled_manual_and_the_truncated_head_points_to_it():
    r = _guide()
    assert r["isError"] is False
    guide = json.loads(r["content"][0]["text"])
    raw = mcp.guide_path("zh").read_text(encoding="utf-8")
    assert guide["guide"] == "team-board" and guide["lang"] == "zh"
    assert guide["version"] and f"\nversion: {guide['version']}\n" in raw
    instructions = mcp.load_instructions()
    assert guide["text"] == instructions and "## 不要做的事" in guide["text"]
    assert "board_guide" in instructions[:2048]          # 截断后一定看得到的部分要指到它
    bad = _rpc(FakeBoard(), "tools/call", {"name": "board_guide", "arguments": {"practice": True}})["result"]
    assert bad["isError"] is True and "不认识的参数" in bad["content"][0]["text"]


def test_guide_rereads_the_manual_each_call_and_a_missing_manual_is_an_error(tmp_path, monkeypatch):
    monkeypatch.setattr(mcp, "GUIDE_DIR", tmp_path)
    guide = tmp_path / "guide.zh.md"
    guide.write_text("---\nname: team-board\nversion: 9.9.1\n---\n\n# 旧正文\n", encoding="utf-8")
    b = FakeBoard()
    assert json.loads(_guide(b)["content"][0]["text"]) == {"guide": "team-board", "lang": "zh", "version": "9.9.1", "text": "# 旧正文"}
    guide.write_text("---\nname: team-board\nversion: 9.9.2\n---\n\n# 新正文\n", encoding="utf-8")
    assert json.loads(_guide(b)["content"][0]["text"])["version"] == "9.9.2"    # 手册更新后不用重启 MCP
    guide.unlink()
    missing = _guide(b)
    assert missing["isError"] is True and "录入手册不在" in missing["content"][0]["text"]
    assert b.calls == [] and b.state_calls == []                               # 只读，不碰看板


def test_english_guide_and_tool_descriptions_follow_lang():
    """lang=en：手册下发英文那一份，工具说明、参数报错也是英文，里面不夹中文。"""
    import re
    i18n.set_default("en")
    try:
        text = mcp.load_instructions()
        assert "## Don'ts" in text and "board_guide" in text[:2048] and mcp.load_guide()["lang"] == "en"
        cjk = re.compile(r"[一-鿿]")
        assert not cjk.search(text)
        for tool in mcp.tools():
            assert not cjk.search(json.dumps(tool, ensure_ascii=False)), tool["name"]
        r = _rpc(FakeBoard(), "tools/call", {"name": "board_act", "arguments": {"action": "void"}})["result"]
        assert r["isError"] is True and "missing argument(s): params" in r["content"][0]["text"]
        t = mcp.board_time("2026-09-29 14:30", "primary", {"name": "America/New_York", "label": "New York"},
                           {"name": "Europe/Berlin", "label": "Berlin"})
        assert t["both"] == "09-29 14:30 (New York) = 09-29 20:30 (Berlin)"
    finally:
        i18n.set_default("zh")
    assert "不要做的事" in mcp.load_instructions()
    # 两份手册讲的是同一套东西：同样的工具、同样的章节数
    zh, en = (mcp.guide_path(x).read_text(encoding="utf-8") for x in ("zh", "en"))
    assert zh.count("\n## ") == en.count("\n## ")
    for name in ("board_actions", "board_guide", "board_state", "board_note", "board_time", "board_act", "board_resolve_note"):
        assert name in zh and name in en


# ---- 练手看板：口述说「练手」就全程 practice=true，默认不走练手 ----

def test_practice_flag_routes_reads_and_writes_to_practice_board_and_default_does_not():
    b = FakeBoard()
    _rpc(b, "tools/call", {"name": "board_act", "arguments": {
        "action": "start_stage", "params": {"goal_id": 5, "stage": "测试"}, "practice": True}})
    _rpc(b, "tools/call", {"name": "board_resolve_note", "arguments": {
        "note_id": 9, "summary": "练手录了测试开始", "practice": True}})
    found = _rpc(b, "tools/call", {"name": "board_note", "arguments": {"note_id": 9, "practice": True}})["result"]
    assert found["isError"] is False
    _rpc(b, "tools/call", {"name": "board_state", "arguments": {}})
    _rpc(b, "tools/call", {"name": "board_act", "arguments": {
        "action": "end_stage", "params": {"goal_id": 5, "stage": "测试"}}})
    assert b.calls == [("start_stage", {"goal_id": 5, "stage": "测试"}, True),
                       ("resolve_note", {"note_id": 9, "summary": "练手录了测试开始"}, True),
                       ("end_stage", {"goal_id": 5, "stage": "测试"}, False)]
    assert b.state_calls == [True, False]
    # practice 只认布尔；规则与时间两边一样，board_actions / board_time 不认这个参数
    bad = _rpc(b, "tools/call", {"name": "board_state", "arguments": {"practice": "yes"}})["result"]
    assert bad["isError"] is True and "类型不对" in bad["content"][0]["text"]
    for name in ("board_actions", "board_time"):
        r = _rpc(b, "tools/call", {"name": name, "arguments": {"practice": True}})["result"]
        assert r["isError"] is True and "不认识的参数" in r["content"][0]["text"]
    assert all("practice" in t["inputSchema"]["properties"] for t in mcp.tools()
               if t["name"] in ("board_state", "board_note", "board_act", "board_resolve_note"))


def test_practice_hits_the_practice_api_paths(monkeypatch):
    seen = []
    board = mcp.Board("http://127.0.0.1:1")
    monkeypatch.setattr(board, "request", lambda method, path, body=None, query=None: seen.append((method, path)) or {})
    board.state(practice=True)
    board.act("create", {}, practice=True)
    board.state()
    board.act("create", {})
    board.actions()
    assert seen == [("GET", "/api/board/practice/state"), ("POST", "/api/board/practice/act"),
                    ("GET", "/api/board/state"), ("POST", "/api/board/act"), ("GET", "/api/board/actions")]


def test_language_comes_from_env_then_board_then_fallback(monkeypatch):
    monkeypatch.setenv(mcp.ENV_LANG, "en")
    assert mcp.pick_lang(FakeBoard()) == "en"            # 环境变量优先
    monkeypatch.delenv(mcp.ENV_LANG)
    assert mcp.pick_lang(FakeBoard()) == "zh"            # 不设就问看板
    assert mcp.pick_lang(None, "zh") == "zh" and mcp.pick_lang(None) == "en"
