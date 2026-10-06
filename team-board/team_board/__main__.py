"""命令行入口：`python3 -m team_board <命令>`（或从任何目录 `python3 /path/to/team-board/tb.py <命令>`）。

    init      生成配置文件（人、线、环节、时区、语言、每人一个随机个人令牌）
    seed      往空看板里灌一份虚构团队的示例数据
    start     起看板服务
    act       从终端读写看板（state / actions 只读；写操作要 --execute）
    mcp       MCP 服务（stdio），给 AI 用
    find      给任意一个目标号，找回相关提交与 Issue
    backup    在线备份正式库
    people    列出人、角色和个人令牌

mcp / act / find / people 只用标准库；init / seed / start / backup 需要先 `pip install -r requirements.txt`。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

from team_board import config as config_mod
from team_board import i18n
from team_board.config import ConfigError, config_path, is_loopback, load_config, starter_config
from team_board.i18n import t


def _guess_lang(argv: list[str]) -> str:
    """帮助文字用哪种语言：--lang > 环境变量 TEAM_BOARD_LANG > 已有配置 > 英文。"""
    for i, a in enumerate(argv):
        if a == "--lang" and i + 1 < len(argv) and argv[i + 1] in i18n.LANGS:
            return argv[i + 1]
        if a.startswith("--lang=") and a[7:] in i18n.LANGS:
            return a[7:]
    env = os.environ.get("TEAM_BOARD_LANG", "").lower()
    if env in i18n.LANGS:
        return env
    try:
        return load_config().lang
    except Exception:  # noqa: BLE001 — 还没有配置很正常
        return "en"


def _load(a) -> config_mod.Config:
    return config_mod.use(load_config(a.config))


# ---------------------------------------------------------------- init / people

def cmd_init(a) -> int:
    path = config_path(a.config)
    if path.exists() and not a.force:
        print(t("cli.init.exists", path=path), file=sys.stderr)
        return 2
    raw = starter_config(a.lang, data_dir=a.data_dir, port=a.port, timezone=a.timezone,
                         timezone_label=a.timezone_label, second_timezone=a.second_timezone,
                         second_timezone_label=a.second_timezone_label, auth=a.auth, host=a.host)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)                      # 里面有个人令牌：只有自己能读
    cfg = config_mod.use(config_mod.parse_config(raw))
    print(t("cli.init.done", path=path))
    print(t("cli.init.people"))
    _print_people(cfg)
    print(t("cli.init.next", url=f"http://127.0.0.1:{cfg.port}"))
    return 0


def _print_people(cfg) -> None:
    for p in cfg.persons:
        print("  " + t("cli.people.row", id=p.id, name=p.name, role=p.role, letter=p.letter, token=p.token))


def cmd_people(a) -> int:
    _print_people(_load(a))
    return 0


# ---------------------------------------------------------------- seed / start / backup

def cmd_seed(a) -> int:
    from team_board import seed
    from team_board.board.store import board_db_path, build_practice, connect_board
    cfg = _load(a)
    lang = a.lang or cfg.lang
    if a.practice:
        from team_board.board.state import fold
        from team_board.board.store import load_events
        path = build_practice(cfg.data_dir, from_seed=True, seed_lang=lang)
        conn = connect_board(cfg.data_dir, practice=True)
        n = len(fold(load_events(conn)).goals)
        conn.close()
        print(t("cli.seed.done", n=n, path=path))
        return 0
    conn = connect_board(cfg.data_dir)
    try:
        n = seed.seed_demo(conn, lang)
    except seed.SeedRefused:
        print(t("cli.seed.refused", path=board_db_path(cfg.data_dir)), file=sys.stderr)
        return 2
    finally:
        conn.close()
    print(t("cli.seed.done", n=n, path=board_db_path(cfg.data_dir)))
    return 0


def cmd_start(a) -> int:
    import uvicorn

    from team_board.main import create_app
    cfg = _load(a)
    host, port = a.host or cfg.host, a.port or cfg.port
    if cfg.auth == "local" and not is_loopback(host):
        # 免登录的本地试用模式只许本机访问；要给别的机器用，先改成令牌模式
        print(t("cfg.unsafe_bind", host=host), file=sys.stderr)
        return 2
    shown = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    print(t("cli.start.listening", title=cfg.title, url=f"http://{shown}:{port}", auth=cfg.auth, data=cfg.data_dir))
    # proxy_headers：前面有反向代理时认它转来的 X-Forwarded-Proto（HTTPS 下 cookie 才会带 Secure）
    uvicorn.run(create_app(cfg, background=True), host=host, port=port, proxy_headers=True, log_level="info")
    return 0


def cmd_backup(a) -> int:
    from team_board.board.model import tz, utc_now
    from team_board.board.store import board_db_path
    cfg = _load(a)
    src = board_db_path(cfg.data_dir)
    if not src.exists():
        print(t("cli.backup.no_db", path=src), file=sys.stderr)
        return 2
    folder = Path(a.out).expanduser() if a.out else src.parent / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"board-{utc_now().astimezone(tz()):%Y%m%d-%H%M%S}.sqlite"
    s, d = sqlite3.connect(src), sqlite3.connect(target)
    try:
        s.backup(d)                            # SQLite 在线备份：服务正在写也能拿到一致的一份
    finally:
        s.close()
        d.close()
    print(t("cli.backup.done", path=target))
    return 0


# ---------------------------------------------------------------- act / find（只用标准库）

def _board(a):
    """按 --url / --as / 环境变量 / 本机配置凑出客户端。"""
    from team_board import mcp
    default_url, _ = mcp.local_defaults()
    url = a.url or os.environ.get(mcp.ENV_URL, "") or default_url
    if not url:
        raise mcp.BoardError(t("cli.act.no_url"))
    token = os.environ.get(mcp.ENV_TOKEN, "")
    if getattr(a, "who", None):
        cfg = load_config(a.config)
        person = cfg.person(a.who)
        if person is None:
            raise mcp.BoardError(t("cli.act.no_person", id=a.who))
        token = person.token
    return mcp.Board(url, token)


def cmd_act(a) -> int:
    from team_board import mcp
    params: dict[str, str] = {}
    for item in a.param:
        k, sep, v = item.partition("=")
        if not sep or not k:
            print(t("cli.act.param_format", item=repr(item)), file=sys.stderr)
            return 2
        if k in params:
            print(t("cli.act.param_dup", key=k), file=sys.stderr)
            return 2
        params[k] = v
    if a.action in ("state", "actions", "sync") and params:
        print(t("cli.act.no_params", action=a.action), file=sys.stderr)
        return 2
    try:
        board = _board(a)
        if a.action == "state":
            data = board.state(a.practice)
        elif a.action == "actions":
            data = board.actions()
        else:
            path = "/api/board/sync" if a.action == "sync" else f"{board._api(a.practice)}/act"
            body = None if a.action == "sync" else {"action": a.action, "params": params}
            if not a.execute:
                print(t("cli.act.dry", url=board.base + path))
                if body:
                    print(json.dumps(body, ensure_ascii=False, indent=2))
                print(t("cli.act.dry_hint"))
                return 0
            data = board.request("POST", path, body)
    except (mcp.BoardError, ConfigError) as e:
        print(str(e), file=sys.stderr)
        return 1
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


_NUM_RE = re.compile(r"^(?:[A-Z][1-9]\d*|G[1-9]\d*(?:\.[1-9]\d*)*)$")


def commits(nums: list[str], repo_dir: Path) -> list[str]:
    """提交信息里「Board-Goal: <号>」那一行；号后面是空格或行尾，A1 不会配到 A16。只翻分支与远端。"""
    alt = "|".join(re.escape(n) for n in nums)
    out = subprocess.run(["git", "log", "--branches", "--remotes", "-E", "-i",
                          f"--grep=^Board-Goal: *({alt})([^0-9.]|$)", "--date=format:%m-%d %H:%M",
                          "--format=%h%x09%ad%x09%s"], cwd=repo_dir, capture_output=True, text=True, check=True)
    return [ln for ln in out.stdout.splitlines() if ln.strip()]


def cmd_find(a) -> int:
    """号的换算在看板侧做（GET /api/board/resolve）：三种号对到同一个目标，再拿它的来源号与永久号
    去翻提交信息里的「Board-Goal: <号>」那一行。Issue 取看板上已经和这个目标关联的单。只读。"""
    from team_board import mcp
    num = a.num.strip().upper()
    if not _NUM_RE.match(num):
        print(t("cli.find.bad_num", num=repr(a.num)), file=sys.stderr)
        return 2
    try:
        board = _board(a)
        try:
            goal = board.resolve(num, a.practice)
        except mcp.BoardError as e:
            if "HTTP 404" not in str(e):
                raise
            print(t("cli.find.miss", num=num), file=sys.stderr)
            return 1
    except (mcp.BoardError, ConfigError) as e:
        print(str(e), file=sys.stderr)
        return 1
    nums = [n for n in dict.fromkeys((goal.get("source"), goal["permanent"])) if n]
    print(t("cli.find.head", num=num, gnum=goal["gnum"], title=goal["title"], owner=goal.get("owner") or "",
            status=goal.get("status") or ""))
    print(t("cli.find.same", gnum=goal["gnum"], permanent=goal["permanent"],
            source=t("cli.find.source", source=goal["source"]) if goal.get("source") else t("cli.find.no_source")))
    try:
        found = commits(nums, Path(a.repo))
    except (subprocess.CalledProcessError, OSError) as e:
        found = []
        print(t("cli.find.git_failed", error=getattr(e, "stderr", "") or e))
    print(t("cli.find.commits", n=len(found), nums=" / ".join(nums)))
    for ln in found:
        sha, at, subject = ln.split("\t", 2)
        print(f"  {sha}  {at}  {subject}")
    if not found:
        print(t("cli.find.nothing"))
    issues = goal.get("issues") or []
    print(t("cli.find.issues", n=len(issues)))
    for i in issues:
        print(f"  {i.get('repo') or ''}#{i['number']}" + (f"  {i['title']}" if i.get("title") else ""))
    if not issues:
        print(t("cli.find.nothing"))
    return 0


# ---------------------------------------------------------------- 入口

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="team_board", description=t("cli.desc"))
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name: str, fn, *, config: bool = True):
        p = sub.add_parser(name, help=t(f"cli.cmd.{name}"), description=t(f"cli.cmd.{name}"))
        p.set_defaults(fn=fn)
        if config:
            p.add_argument("--config", default=None, help=t("cli.arg.config"))
        return p

    p = add("init", cmd_init)
    p.add_argument("--lang", choices=i18n.LANGS, default="zh", help=t("cli.arg.lang"))
    p.add_argument("--data-dir", default=config_mod.DEFAULT_DATA_DIR, help=t("cli.arg.data_dir"))
    p.add_argument("--host", default="127.0.0.1", help=t("cli.arg.host"))
    p.add_argument("--port", type=int, default=config_mod.DEFAULT_PORT, help=t("cli.arg.port"))
    p.add_argument("--timezone", default=None, help=t("cli.arg.timezone"))
    p.add_argument("--timezone-label", default="", help=t("cli.arg.timezone_label"))
    p.add_argument("--second-timezone", default=None, help=t("cli.arg.second_timezone"))
    p.add_argument("--second-timezone-label", default="", help=t("cli.arg.second_timezone_label"))
    p.add_argument("--auth", choices=config_mod.AUTH_MODES, default="local", help=t("cli.arg.auth"))
    p.add_argument("--force", action="store_true", help=t("cli.arg.force"))

    p = add("seed", cmd_seed)
    p.add_argument("--lang", choices=i18n.LANGS, default=None, help=t("cli.arg.lang"))
    p.add_argument("--practice", action="store_true", help=t("cli.arg.seed_practice"))

    p = add("start", cmd_start)
    p.add_argument("--host", default=None, help=t("cli.arg.host"))
    p.add_argument("--port", type=int, default=None, help=t("cli.arg.port"))

    p = add("backup", cmd_backup)
    p.add_argument("--out", default=None, help=t("cli.arg.out"))

    add("people", cmd_people)

    for name, fn in (("act", cmd_act), ("find", cmd_find)):
        p = add(name, fn)
        if name == "act":
            p.add_argument("action", help=t("cli.arg.action"))
            p.add_argument("--param", action="append", default=[], metavar="KEY=VALUE", help=t("cli.arg.param"))
            p.add_argument("--execute", action="store_true", help=t("cli.arg.execute"))
        else:
            p.add_argument("num", help=t("cli.arg.num"))
            p.add_argument("--repo", default=".", help=t("cli.arg.repo"))
        p.add_argument("--url", default="", help=t("cli.arg.url"))
        p.add_argument("--as", dest="who", default=None, help=t("cli.arg.as"))
        p.add_argument("--practice", action="store_true", help=t("cli.arg.practice"))

    sub.add_parser("mcp", help=t("cli.cmd.mcp"), add_help=False)
    return ap


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "mcp":              # MCP 有自己的参数，整段交给它
        from team_board import mcp
        return mcp.main(argv[1:])
    i18n.set_default(_guess_lang(argv))
    a = build_parser().parse_args(argv)
    try:
        return a.fn(a)
    except ConfigError as e:
        print(str(e), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
