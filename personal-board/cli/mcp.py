"""MCP server (stdio) of the personal board: lets an AI log each conversation's progress on the board.

  python3 /path/to/personal-board/cli/mcp.py            # the command to register in Claude Code / Codex
  python3 /path/to/personal-board/cli/mcp.py --check    # self-check: data, tools, guide

All rules live in app/actions.py; this file only passes requests through. It opens the local database
directly, without HTTP, so logging works even when the web page is not running (sqlite WAL handles several
processes reading and writing). How the AI should file, log and wrap up is written in the packaged guide
(app/guide.<lang>.md), sent to the AI as `instructions` at start-up. stdout carries protocol messages only;
logs go to stderr. Standard library only.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import points, settings, team  # noqa: E402
from app.actions import ActionError, action_specs, values  # noqa: E402
from app.i18n import t  # noqa: E402
from app.model import both_zones, local_day, parse_ts, utc_now, zoned  # noqa: E402
from app.mutation import act  # noqa: E402
from app.settings import load_config  # noqa: E402
from app.store import db_path, open_db  # noqa: E402
from app.view import goal_detail, pending_entries, state, timeline  # noqa: E402

SERVER_NAME = "personal-board"
PREFIX = "personal_board_"
SERVER_VERSION = "1.0.0"
PROTOCOL_VERSION = "2025-06-18"
GUIDE_DIR = Path(__file__).resolve().parents[1] / "app"
ENV_PRACTICE = "PERSONAL_BOARD_PRACTICE"


def guide_path() -> Path:
    return GUIDE_DIR / f"guide.{settings.lang()}.md"


def log(msg: str) -> None:
    print(f"personal-board-mcp: {msg}", file=sys.stderr, flush=True)


class McpError(Exception):
    pass


_TIME_RE = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})[ T](\d{1,2}):(\d{2})(?::(\d{2}))?$")


def board_time(when: str | None, zone: str | None) -> dict:
    try:
        zname = points.parse_zone(zone)
    except ValueError as e:
        raise McpError(str(e).replace("point_zone", "zone")) from None
    tz = ZoneInfo(zname)
    if not when:
        dt, source = datetime.now(timezone.utc), t("mcp.now")
    else:
        m = _TIME_RE.match(when.strip())
        if m:
            y, mo, d, h, mi, s = (int(x or 0) for x in m.groups())
            dt = datetime(y, mo, d, h, mi, s, tzinfo=tz)
        else:
            try:
                dt = datetime.fromisoformat(when.strip().replace("Z", "+00:00"))
            except ValueError:
                raise McpError(t("mcp.bad_when")) from None
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=tz)
        source = when + t("paren", x=settings.label_of_zone(zname))
    return {"input": source,
            "zones": [{"zone": z["name"], "label": z["label"], "text": zoned(dt, z, "%Y-%m-%d %H:%M")} for z in settings.zones()],
            "both": both_zones(dt),
            "occurred_at": dt.astimezone(settings.tz()).isoformat(timespec="seconds")}


def tools() -> list[dict]:
    """The tool list in the configured language."""
    n = lambda name: PREFIX + name  # noqa: E731
    obj = lambda props=None, required=(): {"type": "object", "properties": props or {}, **({"required": list(required)} if required else {}),  # noqa: E731
                                           "additionalProperties": False}
    s = lambda key: {"type": "string", "description": t(key, letter=settings.person()["letter"])}  # noqa: E731
    return [
        {"name": n("state"), "description": t("mcp.state"), "inputSchema": obj({"day": s("mcp.p.day")})},
        {"name": n("goal"), "description": t("mcp.goal"), "inputSchema": obj({"goal": s("mcp.p.goal")}, ["goal"])},
        {"name": n("timeline"), "description": t("mcp.timeline"), "inputSchema": obj({"from": s("mcp.p.iso"), "to": s("mcp.p.iso")}, ["from", "to"])},
        {"name": n("pending"), "description": t("mcp.pending"), "inputSchema": obj()},
        {"name": n("actions"), "description": t("mcp.actions"), "inputSchema": obj()},
        {"name": n("guide"), "description": t("mcp.guide"), "inputSchema": obj()},
        {"name": n("time"), "description": t("mcp.time"), "inputSchema": obj({"when": s("mcp.p.when"), "zone": s("mcp.p.zone")})},
        {"name": n("act"), "description": t("mcp.act", actions=", ".join(action_specs())),
         "inputSchema": obj({"request_id": s("mcp.p.request_id"), "action": s("mcp.p.action"),
                             "params": {"type": "object", "description": t("mcp.p.params")}}, ["action", "params"])},
        {"name": n("pull"), "description": t("mcp.pull"), "inputSchema": obj()},
    ]


def _check_args(tool: dict, args: dict) -> None:
    schema = tool["inputSchema"]
    extra = set(args) - set(schema["properties"])
    if extra:
        raise McpError(t("mcp.unknown_args", tool=tool["name"], keys=t("sep").join(sorted(extra))))
    missing = [k for k in schema.get("required", []) if k not in args]
    if missing:
        raise McpError(t("mcp.missing_args", tool=tool["name"], keys=t("sep").join(missing)))
    for k, v in args.items():
        kind = schema["properties"][k].get("type")
        ok = {"string": lambda x: isinstance(x, str), "object": lambda x: isinstance(x, dict),
              "boolean": lambda x: isinstance(x, bool), "integer": lambda x: isinstance(x, int) and not isinstance(x, bool)}[kind](v)
        if not ok:
            raise McpError(t("mcp.bad_type", tool=tool["name"], key=k, type=kind))


def read_guide() -> tuple[str, str]:
    """(version, body) of the packaged guide in the configured language; the front matter is stripped."""
    path = guide_path()
    if not path.is_file():
        raise McpError(t("mcp.no_guide", path=path))
    raw = path.read_text(encoding="utf-8")
    head, body = "", raw
    if raw.startswith("---"):
        _, head, body = raw.split("---", 2)
    version = next((line.split(":", 1)[1].strip() for line in head.splitlines() if line.startswith("version:")), "")
    return version, body.strip()


def load_instructions() -> str:
    return read_guide()[1]


class Server:
    def __init__(self, practice: bool, *, cfg=None, conn=None):
        self.cfg = settings.use(cfg if cfg is not None else load_config())
        self.practice = practice
        self.conn = conn if conn is not None else open_db(db_path(practice))

    def call(self, name: str, args: dict):
        tool = next((x for x in tools() if x["name"] == name), None)
        if tool is None:
            raise McpError(t("mcp.no_tool", name=name))
        _check_args(tool, args)
        now = utc_now()
        name = name[len(PREFIX):]
        if name == "state":
            day = date.fromisoformat(args["day"]) if args.get("day") else local_day(now)
            return state(self.conn, day, now, "practice" if self.practice else "")
        if name == "goal":
            try:
                return goal_detail(self.conn, args["goal"], now)
            except KeyError:
                raise McpError(t("err.no_goal", key=args["goal"], example=f"{settings.person()['letter']}19")) from None
        if name == "timeline":
            return timeline(self.conn, parse_ts(args["from"]), parse_ts(args["to"]), now)
        if name == "pending":
            return {"entries": pending_entries(self.conn),
                    "note": t("mcp.pending_note") if settings.team_enabled() else t("team.off")}
        if name == "actions":
            return {"actions": action_specs(), "values": values(), "note": t("mcp.actions_note")}
        if name == "guide":
            # The same text as `instructions`, read fresh each time; the version tells which edition was read.
            version, text = read_guide()
            return {"guide": SERVER_NAME, "version": version, "lang": settings.lang(), "text": text}
        if name == "time":
            return board_time(args.get("when"), args.get("zone"))
        if name == "act":
            try:
                return act(self.conn, args["action"], args["params"], args.get("request_id"))
            except ActionError as e:
                raise McpError(e.message) from None
        if name == "pull":
            if self.practice:
                raise McpError(t("http.mode_no_pull"))
            r = team.pull(self.conn, now)
            if not r["ok"]:
                raise McpError(r["error"])
            return r
        raise AssertionError(name)


def handle(server: Server, instructions: str, msg: dict) -> dict | None:
    method, rid, params = msg.get("method"), msg.get("id"), msg.get("params") or {}
    if method == "initialize":
        result = {"protocolVersion": PROTOCOL_VERSION, "capabilities": {"tools": {}},
                  "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION}, "instructions": instructions}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": tools()}
    elif method == "tools/call":
        try:
            out = server.call(str(params.get("name", "")), params.get("arguments") or {})
            result = {"content": [{"type": "text", "text": json.dumps(out, ensure_ascii=False, indent=1)}], "isError": False}
        except McpError as e:
            result = {"content": [{"type": "text", "text": str(e)}], "isError": True}
        except Exception as e:  # any odd argument shape goes back to the AI; the process must not die — that would cut this conversation's logging channel
            log(f"tools/call failed: {e!r}")
            result = {"content": [{"type": "text", "text": t("http.bad_params", error=e)}], "isError": True}
    elif rid is None:
        return None
    else:
        return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": t("mcp.bad_method", method=method)}}
    if rid is None:
        return None
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def serve(server: Server) -> int:
    instructions = load_instructions()
    log(f"data {db_path(server.practice)}, {len(tools())} tools, guide {len(instructions)} chars")
    out = sys.stdout
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            out.write(json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": t("http.not_json")}}) + "\n")
            out.flush()
            continue
        resp = handle(server, instructions, msg)
        if resp is not None:
            out.write(json.dumps(resp, ensure_ascii=False) + "\n")
            out.flush()
    return 0


def check(server: Server) -> int:
    version, instructions = read_guide()
    s = server.call(PREFIX + "state", {})
    me = settings.person()
    print(t("mcp.check.data", db=db_path(server.practice), mode=t("mode.practice") if server.practice else t("mode.main"),
            name=me["name"], letter=me["letter"]))
    print(t("mcp.check.guide", path=guide_path(), version=version, chars=len(instructions)))
    print(t("mcp.check.summary", goals=sum(len(ln["goals"]) for ln in s["lines"]), pending=s["header"]["pending_count"],
            team=s["header"]["team_pulled"] or t("cli.team_off")))
    print(t("mcp.check.tools", tools=t("sep").join(x["name"] for x in tools())))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="board mcp", description="Personal Board MCP server (stdio)")
    ap.add_argument("--practice", action="store_true", help=f"use the practice data (or set {ENV_PRACTICE}=1)")
    ap.add_argument("--check", action="store_true", help="read-only self-check, then exit")
    a = ap.parse_args(argv)
    practice = a.practice or os.environ.get(ENV_PRACTICE) == "1"
    try:
        server = Server(practice)
        return check(server) if a.check else serve(server)
    except (McpError, FileNotFoundError, ValueError) as e:
        log(str(e))
        return 1


if __name__ == "__main__":
    sys.exit(main())
