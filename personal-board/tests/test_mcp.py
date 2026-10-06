"""Walk the MCP server through initialize / tools/list / tools/call in a temporary data directory, in both languages."""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CJK = re.compile(r"[一-鿿]")


def _rpc(proc, i, method, params=None):
    proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": i, "method": method, "params": params or {}}) + "\n")
    proc.stdin.flush()
    return json.loads(proc.stdout.readline())


def _start(tmp_path, *init_args):
    env = dict(os.environ, PERSONAL_BOARD_DATA=str(tmp_path / "mcp"))
    env.pop("PERSONAL_BOARD_PRACTICE", None)
    subprocess.run([sys.executable, str(ROOT / "board"), "init", "--id", "linxia", "--letter", "C", "--port", "1", *init_args],
                   env=env, check=True, capture_output=True)
    proc = subprocess.Popen([sys.executable, str(ROOT / "cli/mcp.py")], env=env, stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return proc, env


def test_mcp_roundtrip(tmp_path):
    proc, _ = _start(tmp_path, "--lang", "zh", "--name", "林夏")
    try:
        init = _rpc(proc, 1, "initialize", {"protocolVersion": "2025-06-18"})
        assert init["result"]["serverInfo"]["name"] == "personal-board"
        assert "个人看板手册" in init["result"]["instructions"] and "personal_board_guide" in init["result"]["instructions"]
        tools = _rpc(proc, 2, "tools/list")["result"]["tools"]
        names = [x["name"] for x in tools]
        assert names == ["personal_board_" + n for n in ("state", "goal", "timeline", "pending", "actions", "guide", "time", "act", "pull")]
        assert "只读" in tools[0]["description"]
        r = _rpc(proc, 3, "tools/call", {"name": "personal_board_act", "arguments": {"action": "goal_create", "params": {"title": "试", "line": "个人事项"}}})
        assert r["result"]["isError"] is False
        gnum = json.loads(r["result"]["content"][0]["text"])["gnum"]
        assert gnum == "C1"
        r = _rpc(proc, 4, "tools/call", {"name": "personal_board_act", "arguments": {"action": "stage_start", "params": {"goal": gnum, "stage": "瞎写"}}})
        assert r["result"]["isError"] is True and "环节只能是" in r["result"]["content"][0]["text"]
        s = json.loads(_rpc(proc, 5, "tools/call", {"name": "personal_board_state", "arguments": {}})["result"]["content"][0]["text"])
        assert next(ln for ln in s["lines"] if ln["name"] == "个人事项")["goals"][0]["gnum"] == gnum
        g = json.loads(_rpc(proc, 6, "tools/call", {"name": "personal_board_guide", "arguments": {}})["result"]["content"][0]["text"])
        assert g["lang"] == "zh" and g["version"] and g["text"] == init["result"]["instructions"]
        # the same request_id with the same parameters is answered from the receipt instead of writing twice
        args = {"action": "todo_add", "params": {"text": "只记一次"}, "request_id": "0123456789abcdef-retry"}
        first = _rpc(proc, 7, "tools/call", {"name": "personal_board_act", "arguments": args})["result"]["content"][0]["text"]
        again = _rpc(proc, 8, "tools/call", {"name": "personal_board_act", "arguments": args})["result"]["content"][0]["text"]
        assert first == again
        # no team board is configured by `init`: nothing is unpushed and a pull says so instead of failing to connect
        p = json.loads(_rpc(proc, 9, "tools/call", {"name": "personal_board_pending", "arguments": {}})["result"]["content"][0]["text"])
        assert p["entries"] == [] and "没有连团队看板" in p["note"]
        r = _rpc(proc, 10, "tools/call", {"name": "personal_board_pull", "arguments": {}})
        assert r["result"]["isError"] is True and "没有连团队看板" in r["result"]["content"][0]["text"]
        # common argument mistakes must not kill the process
        for i, (name, args) in enumerate([("personal_board_state", {"day": "10-02"}), ("personal_board_timeline", {"from": "2026-10-01", "to": "2026-10-02"}),
                                          ("personal_board_act", {"action": "todo_done", "params": {"todo_id": "#9"}}),
                                          ("personal_board_act", {"action": "sync_mark", "params": {"entry_ids": "L3", "status": "pushed"}}),
                                          ("personal_board_act", {"action": "log", "params": {"goal": gnum, "text": "x", "_sync": "pushed"}}),
                                          ("personal_board_time", {"zone": "Mars/Olympus"}), ("no_such_tool", {})], start=20):
            r = _rpc(proc, i, "tools/call", {"name": name, "arguments": args})
            assert r["result"]["isError"] is True, (name, args, r)
        assert proc.poll() is None
    finally:
        proc.stdin.close()
        proc.wait(timeout=10)


def test_mcp_in_english(tmp_path):
    """lang=en: instructions, tool descriptions, the action reference, value tables and errors are all English, and the
    time tool writes one zone or two depending on the config."""
    proc, env = _start(tmp_path, "--lang", "en", "--name", "Alex", "--second-timezone", "Asia/Tokyo")
    try:
        init = _rpc(proc, 1, "initialize", {"protocolVersion": "2025-06-18"})
        text = init["result"]["instructions"]
        assert text.startswith("# Personal Board guide") and not CJK.search(text)
        tools = _rpc(proc, 2, "tools/list")["result"]["tools"]
        blob = json.dumps(tools, ensure_ascii=False)
        assert not CJK.search(blob) and "Read-only" in tools[0]["description"]
        acts = _rpc(proc, 3, "tools/call", {"name": "personal_board_actions", "arguments": {}})["result"]["content"][0]["text"]
        assert not CJK.search(acts)
        a = json.loads(acts)
        assert a["values"]["line"] == ["Product", "Growth", "Operations", "Team", "Personal"]
        assert a["values"]["stage"] == ["Business", "Product", "Design", "Dev", "Test"]
        assert a["values"]["kind"]["digest"] == "Digest" and a["values"]["point_zone"] == {"America/Los_Angeles": "Los Angeles", "Asia/Tokyo": "Tokyo"}
        assert "birth number" in a["actions"]["goal_create"]["what"] and "C19" in a["actions"]["goal_create"]["what"]
        r = _rpc(proc, 4, "tools/call", {"name": "personal_board_act", "arguments": {"action": "goal_create", "params": {"title": "Try", "line": "Nowhere"}}})
        assert r["result"]["isError"] is True and "line must be one of Product, Growth" in r["result"]["content"][0]["text"]
        r = _rpc(proc, 5, "tools/call", {"name": "personal_board_act", "arguments": {"action": "goal_create", "params": {"title": "Try", "line": "Product"}}})
        assert json.loads(r["result"]["content"][0]["text"])["gnum"] == "C1"
        tm = json.loads(_rpc(proc, 6, "tools/call", {"name": "personal_board_time", "arguments": {"when": "2026-10-02 09:30"}})["result"]["content"][0]["text"])
        assert tm["both"] == "10-02 09:30 (Los Angeles) = 10-03 01:30 (Tokyo)" and tm["occurred_at"] == "2026-10-02T09:30:00-07:00"
        tm = json.loads(_rpc(proc, 7, "tools/call", {"name": "personal_board_time", "arguments": {"when": "2026-10-03 01:30", "zone": "second"}})["result"]["content"][0]["text"])
        assert tm["occurred_at"] == "2026-10-02T09:30:00-07:00"
        s = _rpc(proc, 8, "tools/call", {"name": "personal_board_state", "arguments": {}})["result"]["content"][0]["text"]
        assert not CJK.search(s) and "Created: Try" in s
    finally:
        proc.stdin.close()
        proc.wait(timeout=10)
    out = subprocess.run([sys.executable, str(ROOT / "board"), "mcp", "--check"], env=env, capture_output=True, text=True)
    assert out.returncode == 0 and "personal_board_act" in out.stdout and not CJK.search(out.stdout)


def test_single_zone_time_writes_one_zone(tmp_path):
    proc, _ = _start(tmp_path, "--lang", "en")
    try:
        _rpc(proc, 1, "initialize", {"protocolVersion": "2025-06-18"})
        tm = json.loads(_rpc(proc, 2, "tools/call", {"name": "personal_board_time", "arguments": {"when": "2026-10-02 09:30"}})["result"]["content"][0]["text"])
        assert tm["both"] == "10-02 09:30 (Los Angeles)" and len(tm["zones"]) == 1
    finally:
        proc.stdin.close()
        proc.wait(timeout=10)
