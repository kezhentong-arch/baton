"""Command line of the personal board. Run it through the `board` launcher next to this package:

  ./board init [--lang en|zh] [--name Alex] [--letter A] [--timezone America/Los_Angeles] [--port 10990]
  ./board seed [--lang en|zh]              fill the empty board with the fictional demo data
  ./board seed --case FILE                 fill the empty board from a case pack (someone's exported board)
  ./board export-case FILE                 export the main board as a case pack
  ./board start | stop | status | open     the local server (one process serves main, /sample/ and /practice/)
  ./board serve                            run in the foreground (debugging)
  ./board pull                             pull my goals from the team board (only when one is configured)
  ./board practice --execute               rebuild the practice database (main data mirror + hypothetical cases)
  ./board reset --execute                  back the main board up, then empty it to start your own
  ./board backup --execute                 online backup of the database, keeping the latest 30
  ./board app --execute                    macOS: install a double-click launcher into ~/Applications
  ./board mcp [--check] [--practice]       the MCP server (stdio) for Claude Code / Codex

Data lives in ~/.local/share/personal-board/ (override with PERSONAL_BOARD_DATA). Standard library only.
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import shlex
import signal
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import settings, team  # noqa: E402
from app.i18n import t  # noqa: E402
from app.model import utc_now  # noqa: E402
from app.settings import DEFAULT_PORT, DEFAULT_TIMEZONE, LANGS, data_dir, load_config, save_config  # noqa: E402
from app.store import db_path, open_db, set_meta  # noqa: E402

APP_MARK = "personal-board-launcher"   # written into the launcher so `app` never overwrites someone else's application


def _pidfile() -> Path:
    return data_dir() / "server.pid"


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _running() -> int | None:
    p = _pidfile()
    if not p.is_file():
        return None
    try:
        pid = int(p.read_text().strip())
    except ValueError:
        return None
    return pid if _alive(pid) else None


def _cfg() -> dict:
    return settings.use(load_config())


def cmd_init(a) -> int:
    if settings.config_path().exists() and not a.force:
        print(t("cli.init_exists", lang=a.lang, path=settings.config_path()), file=sys.stderr)
        return 1
    pid = a.id or getpass.getuser()
    cfg = settings.normalize(settings.default_config(
        a.lang, person_id=pid, name=a.name or pid, letter=a.letter, port=a.port,
        timezone=a.timezone, timezone_label=a.timezone_label,
        second_timezone=a.second_timezone, second_timezone_label=a.second_timezone_label,
        team_url=a.team_board_url, team_token=a.team_board_token))
    if not cfg["team_board"]["owner"]:
        cfg["team_board"].pop("owner")
    p = save_config(cfg)
    try:
        p.chmod(0o600)   # the file may hold the team-board token
    except OSError:
        pass
    settings.use(cfg)
    conn = open_db(db_path(False))
    with conn:
        set_meta(conn, "person", cfg["person"]["id"])
    conn.close()
    from app.sample import build_practice
    build_practice()
    me = cfg["person"]
    print(t("cli.init_done", path=p, name=me["name"], id=me["id"], letter=me["letter"], port=cfg["port"],
            zones=" + ".join(z["name"] for z in settings.zones()),
            team=cfg["team_board"]["base_url"] or t("cli.team_off"), db=db_path(False)))
    return 0


def cmd_seed(a) -> int:
    from app.sample import build_practice
    from app.seed import seed_demo
    cfg = _cfg()
    conn = open_db(db_path(False))
    try:
        if a.case:   # a case pack: someone's exported board, loaded as a worked example
            from app import case
            data = case.load_case_file(Path(a.case))
            case.check_case(data)
            if a.adopt_config:
                case.adopt_config(data)
                print(t("cli.case_adopted"))
            missing = case.missing_names(data)
            n = case.import_case(conn, data, utc_now())
            print(t("cli.case_done", label=case.case_label(data), db=db_path(False), goals=n["goals"], entries=n["entries"], todos=n["todos"]))
            if missing["lines"] or missing["stages"]:
                print(t("cli.case_missing", lines=t("sep").join(missing["lines"]) or t("cli.none"),
                        stages=t("sep").join(missing["stages"]) or t("cli.none")))
        else:
            r = seed_demo(conn, a.lang or cfg["lang"], utc_now())
            print(t("cli.seed_done", goals=r["goals"], entries=r["entries"], db=db_path(False)))
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 1
    finally:
        conn.close()
    build_practice()   # practice = a mirror of the main data, so it is rebuilt with it
    return 0


def cmd_export_case(a) -> int:
    """Write the main board to a case pack (goals, entries, to-dos; dictations are left out)."""
    from app import case
    _cfg()
    conn = open_db(db_path(False))
    try:
        data = case.export_case(conn, utc_now())
        p = case.write_case(conn, utc_now(), Path(a.file))
    finally:
        conn.close()
    n = {tb: len(rows) for tb, rows in data["tables"].items()}
    print(t("cli.export_done", path=p, goals=n["goals"], entries=n["entries"], todos=n["todos"]))
    return 0


def cmd_practice(a) -> int:
    from app.sample import build_practice
    _cfg()
    if not a.execute:
        print(t("cli.practice_dry"))
        return 0
    print(t("cli.practice_done", path=build_practice()))
    return 0


def cmd_serve(a) -> int:
    cfg = _cfg()
    from app.server import serve
    serve(cfg, a.port or cfg["port"])
    return 0


def cmd_start(a) -> int:
    cfg = _cfg()
    port = a.port or cfg["port"]
    pid = _running()
    if pid:
        print(t("cli.already_running", pid=pid, port=port))
        return 0
    log = data_dir() / "server.log"
    cmd = [sys.executable, str(Path(__file__).resolve()), "serve", "--port", str(port)]
    with open(log, "ab") as out:
        proc = subprocess.Popen(cmd, stdout=out, stderr=subprocess.STDOUT, start_new_session=True, cwd=str(ROOT))
    _pidfile().write_text(str(proc.pid))
    for _ in range(40):
        if proc.poll() is not None:
            break
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=1) as r:
                if r.status == 200 and json.loads(r.read()).get("service") == "personal-board":
                    print(t("cli.started", pid=proc.pid, port=port, log=log))
                    return 0
        except Exception:
            time.sleep(0.25)
    _pidfile().unlink(missing_ok=True)
    print(t("cli.start_failed_exited" if proc.poll() is not None else "cli.start_failed_silent", log=log), file=sys.stderr)
    return 1


def cmd_stop(a) -> int:
    pid = _running()
    if not pid:
        _pidfile().unlink(missing_ok=True)
        print(t("cli.not_running"))
        return 0
    os.kill(pid, signal.SIGTERM)
    for _ in range(40):
        if not _alive(pid):
            break
        time.sleep(0.25)
    _pidfile().unlink(missing_ok=True)
    print(t("cli.stopped", pid=pid))
    return 0


def cmd_status(a) -> int:
    cfg = _cfg()
    pid = _running()
    print(t("cli.status_running", pid=pid, port=cfg["port"], data=data_dir()) if pid
          else t("cli.status_stopped", port=cfg["port"], data=data_dir()))
    return 0


def cmd_open(a) -> int:
    cfg = _cfg()
    url = f"http://127.0.0.1:{a.port or cfg['port']}/"
    if sys.platform == "darwin":
        subprocess.run(["open", url], check=False)
    else:
        print(url)
    return 0


def cmd_app(a) -> int:
    """Install a macOS application into ~/Applications: double-click = start the local server (if it is not
    running) and open the board in the browser. A pure shell: a launcher script, an Info.plist and an icon made
    from static/icon.png. Nothing else is installed."""
    cfg = _cfg()
    if sys.platform != "darwin":
        print(t("cli.app_macos_only"), file=sys.stderr)
        return 1
    name = t("app.name")
    app = Path.home() / "Applications" / f"{name}.app"
    launcher = app / "Contents/MacOS/launch"
    if app.exists() and not (launcher.is_file() and APP_MARK in launcher.read_text(errors="replace")):
        print(t("cli.app_foreign", path=app), file=sys.stderr)   # an application of the same name that this tool did not create
        return 1
    if not a.execute:
        print(t("cli.app_dry", path=app))
        return 0
    macos, res = app / "Contents/MacOS", app / "Contents/Resources"
    macos.mkdir(parents=True, exist_ok=True)
    res.mkdir(parents=True, exist_ok=True)
    url = f"http://127.0.0.1:{cfg['port']}/"
    log = data_dir() / "launcher.log"
    alert = json.dumps(t("cli.app_alert"), ensure_ascii=False)
    env = f"export {settings.ENV_DATA}={shlex.quote(str(data_dir()))}\n" if os.environ.get(settings.ENV_DATA) else ""
    launcher.write_text(f"""#!/bin/bash
# {APP_MARK}: generated by `board app --execute`; do not edit — regenerate after moving the folder or changing Python.
{env}LOG={shlex.quote(str(log))}
if ! {shlex.quote(sys.executable)} {shlex.quote(str(ROOT / 'cli' / 'board.py'))} start >>"$LOG" 2>&1; then
  osascript -e 'display alert {alert} message "'"$LOG"'"' >/dev/null 2>&1
  exit 1
fi
# If the board is already open in Chrome, switch to that tab instead of opening another one.
URL={shlex.quote(url)}
if ! osascript - "$URL" <<'EOS' 2>/dev/null | grep -q found; then open "$URL"; fi
on run argv
  set u to item 1 of argv
  tell application "Google Chrome"
    if not running then return "no"
    repeat with w in windows
      set i to 0
      repeat with t in tabs of w
        set i to i + 1
        if URL of t starts with u then
          set active tab index of w to i
          set index of w to 1
          activate
          return "found"
        end if
      end repeat
    end repeat
  end tell
  return "no"
end run
EOS
""")
    launcher.chmod(0o755)
    (app / "Contents/Info.plist").write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>{name}</string>
  <key>CFBundleDisplayName</key><string>{name}</string>
  <key>CFBundleIdentifier</key><string>local.personal-board</string>
  <key>CFBundleVersion</key><string>1.0</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>launch</string>
  <key>CFBundleIconFile</key><string>icon</string>
  <key>LSUIElement</key><true/>
</dict></plist>
""")
    png = ROOT / "app/static/icon.png"
    with tempfile.TemporaryDirectory() as td:
        iconset = Path(td) / "icon.iconset"
        iconset.mkdir()
        for size in (16, 32, 128, 256, 512):
            for scale in (1, 2):
                px = size * scale
                fname = f"icon_{size}x{size}{'@2x' if scale == 2 else ''}.png"
                subprocess.run(["sips", "-z", str(px), str(px), str(png), "--out", str(iconset / fname)], check=True, capture_output=True)
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(res / "icon.icns")], check=True)
    subprocess.run(["touch", str(app)], check=False)  # makes Finder refresh the icon
    print(t("cli.app_done", path=app, url=url, log=log))
    return 0


def cmd_reset(a) -> int:
    """Done with the demo (or starting over): back the main database up to backups/ in the data directory, then
    recreate it empty (person and port unchanged) and rebuild the practice database."""
    from app.seed import reset_main
    cfg = _cfg()
    if not a.execute:
        print(t("cli.reset_dry", db=db_path(False), backups=data_dir() / "backups", name=cfg["person"]["name"]))
        return 0
    r = reset_main(utc_now())
    print(t("cli.reset_done", db=r["main"], backup=r["backup"] or t("cli.no_backup")))
    return 0


def cmd_backup(a) -> int:
    from cli.backup import backup
    _cfg()
    if not a.execute:
        print(t("cli.backup_dry", db=db_path(False)))
        return 0
    print(backup())
    return 0


def cmd_pull(a) -> int:
    _cfg()
    conn = open_db(db_path(False))
    r = team.pull(conn, utc_now())
    print(json.dumps(r, ensure_ascii=False))
    return 0 if r["ok"] else 1


def cmd_mcp(a) -> int:
    from cli.mcp import main as mcp_main
    return mcp_main((["--practice"] if a.practice else []) + (["--check"] if a.check else []))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="board", description="Personal Board")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("init", help="write the config and create the database")
    s.add_argument("--lang", choices=LANGS, default="en")
    s.add_argument("--id", default="", help="your id (default: the OS user name)")
    s.add_argument("--name", default="", help="your display name (default: the id)")
    s.add_argument("--letter", default="", help="one capital letter for your birth numbers (not G or E)")
    s.add_argument("--port", type=int, default=DEFAULT_PORT)
    s.add_argument("--timezone", default=DEFAULT_TIMEZONE, help="main time zone, IANA name")
    s.add_argument("--timezone-label", default="")
    s.add_argument("--second-timezone", default="", help="optional second time zone, IANA name")
    s.add_argument("--second-timezone-label", default="")
    s.add_argument("--team-board-url", default="", help="optional; leave empty to use the board on its own")
    s.add_argument("--team-board-token", default="")
    s.add_argument("--force", action="store_true", help="overwrite an existing config")
    s.set_defaults(fn=cmd_init)
    s = sub.add_parser("seed", help="fill the empty board with the fictional demo data")
    s.add_argument("--lang", choices=LANGS, default="", help="language of the demo text (default: the configured one)")
    s.add_argument("--case", default="", metavar="FILE", help="load a case pack (an exported board) instead of the demo data")
    s.add_argument("--adopt-config", action="store_true", help="with --case: copy the pack's lines and stages into your config first")
    s.set_defaults(fn=cmd_seed)
    s = sub.add_parser("export-case", help="export the main board as a case pack (JSON)")
    s.add_argument("file", metavar="FILE")
    s.set_defaults(fn=cmd_export_case)
    for name, fn in (("serve", cmd_serve), ("start", cmd_start), ("open", cmd_open)):
        s = sub.add_parser(name)
        s.add_argument("--port", type=int, default=0)
        s.set_defaults(fn=fn)
    for name, fn in (("stop", cmd_stop), ("status", cmd_status), ("pull", cmd_pull)):
        sub.add_parser(name).set_defaults(fn=fn)
    for name, fn in (("practice", cmd_practice), ("reset", cmd_reset), ("backup", cmd_backup), ("app", cmd_app)):
        s = sub.add_parser(name)
        s.add_argument("--execute", action="store_true", help="really do it; without it only says what would happen")
        s.set_defaults(fn=fn)
    s = sub.add_parser("mcp", help="the MCP server (stdio)")
    s.add_argument("--practice", action="store_true")
    s.add_argument("--check", action="store_true")
    s.set_defaults(fn=cmd_mcp)
    a = ap.parse_args(argv)
    try:
        return a.fn(a)
    except (FileNotFoundError, settings.ConfigError) as e:
        print(str(e), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
