"""团队看板的 MCP server（stdio）：让 AI 把口述录进看板。

    python3 /path/to/team-board/tb.py mcp            # 给 Claude Code / Codex 当 command 用
    python3 /path/to/team-board/tb.py mcp --check    # 自检：看板连不连得上、工具列表、手册在不在

只做看板 HTTP 接口的薄包装：规则（谁能做什么、缺什么字段、时间先后）全在服务端，这里一条不抄。
AI 该怎么追问、怎么确认，写在包内自带的手册 guide.zh.md / guide.en.md；本进程启动时把它作为
MCP instructions 原文带给 AI。有的客户端只显示 instructions 的前两千字左右，所以另有只读工具
board_guide 现读同一份返回全文。

环境变量：
  TEAM_BOARD_URL    看板地址（本机 http://127.0.0.1:端口 或 https://…）；不设就用本机配置文件里的地址
  TEAM_BOARD_TOKEN  个人令牌：以谁的令牌连，就以谁的身份读写（令牌模式必填；本地试用模式可不填）
  TEAM_BOARD_LANG   zh / en；不设就问看板

同一个站上还有练手看板（/board/practice）：读写工具带 practice=true 就打 /api/board/practice/…，
在练手看板上练「口述 → AI 录入」而不碰正式数据。同一个 MCP 注册，不用另装。

只用标准库。MCP stdio 协议：stdin/stdout 各一行一条 JSON-RPC 2.0；stdout 只写协议消息，日志一律 stderr。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from team_board import __version__, i18n
from team_board.i18n import t

SERVER_NAME = "team-board"
SERVER_VERSION = __version__
PROTOCOL_VERSION = "2025-06-18"
GUIDE_DIR = Path(__file__).resolve().parent
ENV_URL, ENV_TOKEN, ENV_LANG = "TEAM_BOARD_URL", "TEAM_BOARD_TOKEN", "TEAM_BOARD_LANG"


def log(msg: str) -> None:
    print(f"team-board-mcp: {msg}", file=sys.stderr, flush=True)


class BoardError(Exception):
    """看板或传输层的失败，原样带给 AI（isError=true），不转译、不兜底。"""


class Board:
    """看板 HTTP 客户端。身份只由个人令牌决定（Authorization: Bearer）。"""

    def __init__(self, base: str, token: str = ""):
        base = base.rstrip("/")
        self.local = base.startswith(("http://127.0.0.1:", "http://localhost:", "http://[::1]:"))
        if not self.local and not base.startswith("https://"):
            raise BoardError(t("mcp.bad_url", env=ENV_URL))
        self.base, self.token = base, token.strip()
        self._meta: dict | None = None

    def _headers(self) -> dict[str, str]:
        # 自定 User-Agent：urllib 默认的 "Python-urllib/x.y" 常被反向代理或防火墙当成爬虫整站拒绝
        headers = {"User-Agent": f"team-board-client/{__version__}", "X-Board-Via": "ai"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def request(self, method: str, path: str, body: dict | None = None, query: dict | None = None) -> dict:
        headers = self._headers()
        url = f"{self.base}{path}" + (f"?{urllib.parse.urlencode(query)}" if query else "")
        data = None
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode()
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        # 连本机的看板不走系统代理（设了 http_proxy 的机器上，代理不认得 127.0.0.1 上的服务）
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({})) if self.local else urllib.request.build_opener()
        try:
            with opener.open(req, timeout=120) as r:
                raw, status = r.read(), r.status
        except urllib.error.HTTPError as e:
            raw, status = e.read(), e.code
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise BoardError(t("mcp.unreachable", base=self.base, reason=getattr(e, "reason", e))) from None
        try:
            payload = json.loads(raw)
        except ValueError:
            raise BoardError(t("mcp.not_json", status=status, body=repr(raw[:300]))) from None
        if status != 200 or (isinstance(payload, dict) and payload.get("ok") is False):
            reason = payload.get("error") or payload.get("detail") if isinstance(payload, dict) else payload
            if status == 401:
                reason = f"{reason} — {t('mcp.need_token', env=ENV_TOKEN)}"
            raise BoardError(t("mcp.rejected", status=status, reason=reason))
        return payload

    @staticmethod
    def _api(practice: bool) -> str:
        """正式 /api/board，练手 /api/board/practice（服务端按这个前缀选库）。"""
        return "/api/board/practice" if practice else "/api/board"

    def state(self, practice: bool = False) -> dict:
        return self.request("GET", f"{self._api(practice)}/state")

    def actions(self) -> dict:
        return self.request("GET", "/api/board/actions")

    def meta(self) -> dict:
        """语言、时区、我是谁：来自操作说明接口，整个进程只问一次。"""
        if self._meta is None:
            self._meta = self.actions()
        return self._meta

    def act(self, action: str, params: dict, practice: bool = False) -> dict:
        return self.request("POST", f"{self._api(practice)}/act", {"action": action, "params": params})

    def resolve(self, num: str, practice: bool = False) -> dict:
        return self.request("GET", f"{self._api(practice)}/resolve", query={"num": num})


def find_note(state: dict, note_id: int) -> dict:
    """口述清单在看板现状的顶层 notes。"""
    if "notes" not in state:
        raise BoardError(t("mcp.no_notes_field", id=note_id))
    for n in state["notes"]:
        if n.get("id") == note_id:
            return n
    raise BoardError(t("mcp.no_note", id=note_id))


_TIME_RE = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})[ T](\d{1,2}):(\d{2})(?::(\d{2}))?$")


def board_time(when: str | None, zone: str, primary: dict, second: dict | None) -> dict:
    """时间换算。primary / second 是看板配置的主时区、第二时区（{"name", "label"}；没配第二时区就是 None）。
    没配第二时区时，所有「两地都写」的地方只写一地。"""
    if zone == "second" and second is None:
        raise BoardError(t("mcp.no_second_zone"))
    chosen = second if zone == "second" else primary
    tz1 = ZoneInfo(primary["name"])
    tz2 = ZoneInfo(second["name"]) if second else None
    tz = ZoneInfo(chosen["name"])
    if not when:
        dt = datetime.now(timezone.utc)
        source = t("mcp.time_now")
    else:
        m = _TIME_RE.match(when.strip())
        if m:
            y, mo, d, h, mi, s = (int(x or 0) for x in m.groups())
            dt = datetime(y, mo, d, h, mi, s, tzinfo=tz)
        else:
            try:
                dt = datetime.fromisoformat(when.strip().replace("Z", "+00:00"))
            except ValueError:
                raise BoardError(t("mcp.bad_when")) from None
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=tz)
        source = when + t("tz.note", label=chosen["label"])
    a = dt.astimezone(tz1)
    note1 = t("tz.note", label=primary["label"])
    out = {"input": source, "primary": a.strftime("%Y-%m-%d %H:%M") + note1,
           "both": a.strftime("%m-%d %H:%M") + note1, "occurred_at": a.isoformat(timespec="seconds")}
    if tz2 is not None:
        b = dt.astimezone(tz2)
        note2 = t("tz.note", label=second["label"])
        out["second"] = b.strftime("%Y-%m-%d %H:%M") + note2
        out["both"] += t("mcp.both_join") + b.strftime("%m-%d %H:%M") + note2
    return out


def tools() -> list[dict]:
    """工具清单（说明文字跟语言走）。"""
    # 练手开关：口述里写的是「练手看板（练手口述 #N）」就全程带 practice=true，同一次录入不要一半正式一半练手
    practice = {"type": "boolean", "default": False, "description": t("mcp.arg.practice")}
    return [
        {"name": "board_actions", "description": t("mcp.tool.actions"),
         "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
        {"name": "board_guide", "description": t("mcp.tool.guide"),
         "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
        {"name": "board_state", "description": t("mcp.tool.state"),
         "inputSchema": {"type": "object", "properties": {"practice": practice}, "additionalProperties": False}},
        {"name": "board_note", "description": t("mcp.tool.note"),
         "inputSchema": {"type": "object",
                         "properties": {"note_id": {"type": "integer", "minimum": 1, "description": t("mcp.arg.note_id")},
                                        "practice": practice},
                         "required": ["note_id"], "additionalProperties": False}},
        {"name": "board_time", "description": t("mcp.tool.time"),
         "inputSchema": {"type": "object",
                         "properties": {"when": {"type": "string", "description": t("mcp.arg.when")},
                                        "zone": {"type": "string", "enum": ["primary", "second"], "default": "primary",
                                                 "description": t("mcp.arg.zone")}},
                         "additionalProperties": False}},
        {"name": "board_act", "description": t("mcp.tool.act"),
         "inputSchema": {"type": "object",
                         "properties": {"action": {"type": "string", "description": t("mcp.arg.action")},
                                        "params": {"type": "object", "description": t("mcp.arg.params")},
                                        "practice": practice},
                         "required": ["action", "params"], "additionalProperties": False}},
        {"name": "board_resolve_note", "description": t("mcp.tool.resolve_note"),
         "inputSchema": {"type": "object",
                         "properties": {"note_id": {"type": "integer", "minimum": 1},
                                        "summary": {"type": "string", "minLength": 1, "maxLength": 500},
                                        "practice": practice},
                         "required": ["note_id", "summary"], "additionalProperties": False}},
    ]


def _check_args(tool: dict, args: dict) -> None:
    """输入严格：未知、缺失、类型不对，在任何副作用前失败。"""
    schema = tool["inputSchema"]
    extra = set(args) - set(schema["properties"])
    if extra:
        raise BoardError(t("mcp.args_unknown", tool=tool["name"], names=t("sep").join(sorted(extra))))
    missing = [k for k in schema.get("required", []) if k not in args]
    if missing:
        raise BoardError(t("mcp.args_missing", tool=tool["name"], names=t("sep").join(missing)))
    for k, v in args.items():
        spec = schema["properties"][k]
        kind = spec.get("type")
        ok = {"integer": lambda x: isinstance(x, int) and not isinstance(x, bool),
              "string": lambda x: isinstance(x, str), "object": lambda x: isinstance(x, dict),
              "boolean": lambda x: isinstance(x, bool)}[kind](v)
        if not ok:
            raise BoardError(t("mcp.args_type", tool=tool["name"], key=k, type=kind))
        if "enum" in spec and v not in spec["enum"]:
            raise BoardError(t("mcp.args_enum", tool=tool["name"], key=k, options=t("sep").join(spec["enum"])))
        if kind == "integer" and v < spec.get("minimum", v):
            raise BoardError(t("mcp.args_positive", tool=tool["name"], key=k))


def call_tool(board: Board, name: str, args: dict) -> dict | str:
    tool = next((x for x in tools() if x["name"] == name), None)
    if tool is None:
        raise BoardError(t("mcp.no_tool", name=name))
    _check_args(tool, args)
    if name == "board_actions":
        return board.actions()
    if name == "board_guide":
        return load_guide()
    practice = bool(args.get("practice", False))
    if name == "board_state":
        return board.state(practice)
    if name == "board_note":
        return find_note(board.state(practice), args["note_id"])
    if name == "board_time":
        meta = board.meta()
        return board_time(args.get("when"), args.get("zone", "primary"), meta["timezone"], meta.get("second_timezone"))
    if name == "board_act":
        return board.act(args["action"], args["params"], practice)
    if name == "board_resolve_note":
        return board.act("resolve_note", {"note_id": args["note_id"], "summary": args["summary"]}, practice)
    raise AssertionError(name)


def guide_path(lang: str | None = None) -> Path:
    return GUIDE_DIR / f"guide.{lang or i18n.current_lang()}.md"


def _split_guide(path: Path) -> tuple[str, str]:
    """(frontmatter, 正文)。"""
    if not path.is_file():
        raise BoardError(t("mcp.no_guide", path=path))
    raw = path.read_text(encoding="utf-8")
    if raw.startswith("---"):
        _, head, body = raw.split("---", 2)
        return head, body.strip()
    return "", raw.strip()


def load_instructions() -> str:
    return _split_guide(guide_path())[1]


def load_guide() -> dict:
    """board_guide：与 instructions 同一份正文，每次现读（手册更新后不用重启）；版本号取 frontmatter，便于确认读到哪一版。"""
    head, text = _split_guide(guide_path())
    version = next((line.split(":", 1)[1].strip() for line in head.splitlines() if line.startswith("version:")), "")
    return {"guide": SERVER_NAME, "lang": i18n.current_lang(), "version": version, "text": text}


def handle(board: Board, instructions: str, msg: dict) -> dict | None:
    """一条 JSON-RPC 请求 → 一条响应；通知（没有 id）不回。"""
    method, rid, params = msg.get("method"), msg.get("id"), msg.get("params") or {}
    if method == "initialize":
        result = {"protocolVersion": params.get("protocolVersion") or PROTOCOL_VERSION,
                  "capabilities": {"tools": {}},
                  "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                  "instructions": instructions}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": tools()}
    elif method == "tools/call":
        try:
            out = call_tool(board, str(params.get("name", "")), params.get("arguments") or {})
            text = out if isinstance(out, str) else json.dumps(out, ensure_ascii=False, indent=1)
            result = {"content": [{"type": "text", "text": text}], "isError": False}
        except BoardError as e:
            result = {"content": [{"type": "text", "text": str(e)}], "isError": True}
    elif rid is None:
        return None  # notifications/initialized、notifications/cancelled 等
    else:
        return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": t("mcp.no_method", method=method)}}
    if rid is None:
        return None
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def serve(board: Board) -> int:
    instructions = load_instructions()
    log(f"{board.base} · {len(tools())} tools · {guide_path().name} ({len(instructions)} chars)")
    out = sys.stdout
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            out.write(json.dumps({"jsonrpc": "2.0", "id": None,
                                  "error": {"code": -32700, "message": "parse error: not JSON"}}) + "\n")
            out.flush()
            continue
        resp = handle(board, instructions, msg)
        if resp is not None:
            out.write(json.dumps(resp, ensure_ascii=False) + "\n")
            out.flush()
    return 0


def check(board: Board) -> int:
    """自检（只读）：手册在不在、看板通不通、我是谁、工具列表。"""
    instructions = load_instructions()
    acts = board.actions()
    me = acts.get("me") or {}
    print(t("mcp.check.board", base=board.base))
    print(t("mcp.check.me", name=me.get("name", "?"), role=me.get("role", "?")))
    print(t("mcp.check.guide", path=guide_path(), n=len(instructions)))
    print(t("mcp.check.actions", n=len(acts["actions"]), people=t("sep").join(acts["values"]["people"].values())))
    practice = board.state(practice=True)      # 练手接口通不通：练手库不存在时服务端会按此刻的正式数据建一份
    print(t("mcp.check.practice", n=len(practice.get("goals", []))))
    print(t("mcp.check.tools", names=t("sep").join(x["name"] for x in tools())))
    return 0


def local_defaults() -> tuple[str, str]:
    """没设环境变量时：本机有配置文件就用它的地址和语言（同一台电脑上试用，开箱即用）。"""
    try:
        from team_board.config import load_config
        cfg = load_config()
    except Exception:  # noqa: BLE001 — 没有配置文件、或配置在另一台机器上，都正常
        return "", ""
    host = "127.0.0.1" if cfg.host in ("0.0.0.0", "::") else cfg.host
    return f"http://{host}:{cfg.port}", cfg.lang


def pick_lang(board: Board | None, fallback: str = "") -> str:
    lang = os.environ.get(ENV_LANG, "").strip().lower()
    if lang in i18n.LANGS:
        return lang
    if board is not None:
        try:
            lang = board.meta().get("lang", "")
        except BoardError:
            lang = ""
        if lang in i18n.LANGS:
            return lang
    return fallback if fallback in i18n.LANGS else "en"


def main(argv: list[str] | None = None) -> int:
    default_url, default_lang = local_defaults()
    i18n.set_default(pick_lang(None, default_lang))
    ap = argparse.ArgumentParser(prog="team_board mcp", description=t("cli.mcp.desc"))
    ap.add_argument("--url", default=os.environ.get(ENV_URL, "") or default_url, help=t("cli.mcp.url", env=ENV_URL))
    ap.add_argument("--check", action="store_true", help=t("cli.mcp.check"))
    a = ap.parse_args(argv)
    if not a.url:
        ap.error(t("cli.mcp.no_url", env=ENV_URL))
    try:
        board = Board(a.url, os.environ.get(ENV_TOKEN, ""))
        i18n.set_default(pick_lang(board, default_lang))
        return check(board) if a.check else serve(board)
    except BoardError as e:
        log(str(e))
        return 1


if __name__ == "__main__":
    sys.exit(main())
