"""The local web page and HTTP API (standard-library http.server, bound to 127.0.0.1 only).

Three data sets behind URL prefixes: `/` main, `/sample/` example (read-only), `/practice/` practice (play
freely, one-click reset). Pages are static templates with JSON injected; everything on screen is computed in
the browser. There is exactly one write path: POST {prefix}/api/act → actions.apply_action.
"""
from __future__ import annotations

import json
import mimetypes
import re
import sqlite3
import threading
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from app import settings, team
from app.actions import ActionError, action_specs, apply_action, values
from app.i18n import js_table, t
from app.model import VERSION, local_day, parse_ts, utc_now
from app.sample import SampleMirror, build_practice
from app.store import MODES, get_meta, mode_db_path, open_db
from app.view import day_counts, goal_detail, pending_entries, state, timeline

HERE = Path(__file__).resolve().parent
TEMPLATES = HERE / "templates"
STATIC = HERE / "static"
HTML_LANG = {"zh": "zh-CN", "en": "en"}
_T_RE = re.compile(r"\{\{t:([a-z0-9_.]+)\}\}")


def _json_for_html(obj) -> str:
    return json.dumps(obj, ensure_ascii=False).replace("</", "<\\/")


def page_config() -> dict:
    """What the browser needs from the config: language, time zones, stage order, whether a team board is connected."""
    zs = settings.zones()
    return {"lang": settings.lang(), "tz": zs[0]["name"], "tz_label": zs[0]["label"],
            "stages": settings.stage_names(), "team_board": settings.team_enabled()}


def boot_script() -> str:
    """Inline script every page starts with: the translation table, the config, and T(key, vars)."""
    return ("<script>window.__I18N__ = " + _json_for_html(js_table()) + "; window.__CFG__ = " + _json_for_html(page_config()) + ";"
            "window.T = function (k, v) { var s = window.__I18N__[k]; if (s == null) return k;"
            " return v ? s.replace(/\\{(\\w+)\\}/g, function (m, n) { return n in v ? v[n] : m; }) : s; };</script>")


def render(name: str, **inject: str) -> str:
    text = (TEMPLATES / name).read_text(encoding="utf-8")
    text = _T_RE.sub(lambda m: t(m.group(1)), text)
    inject.setdefault("HTML_LANG", HTML_LANG[settings.lang()])
    inject.setdefault("BOOT", boot_script())
    for k, v in inject.items():
        text = text.replace("{{" + k + "}}", v)
    return text


class App:
    def __init__(self, cfg: dict):
        self.cfg = settings.use(cfg)
        self._local = threading.local()
        self.lock = threading.Lock()  # writes are serialised; reads need no lock under sqlite WAL
        self.sample_mirror = SampleMirror(mode_db_path(""))

    def conn(self, mode: str) -> sqlite3.Connection:
        if mode == "sample":  # the example = a live mirror of the main database + hypothetical cases, never a file
            return self.sample_mirror.conn()
        conns = getattr(self._local, "conns", None)
        if conns is None:
            conns = self._local.conns = {}
        if mode not in conns:
            conns[mode] = open_db(mode_db_path(mode))
        return conns[mode]

    AUTO_PULL_AFTER = timedelta(minutes=10)

    def maybe_pull(self) -> None:
        """With a team board connected, pull in the background when the main board has not pulled for 10 minutes
        (a goal created on the team board should show up without anyone clicking). Never blocks the page; a
        failure is kept in meta and shown in the header. Without a team board this does nothing."""
        if not settings.team_enabled() or getattr(self, "_pulling", False):
            return
        last = get_meta(self.conn(""), "team_pulled_at")
        if last and utc_now() - parse_ts(last) < self.AUTO_PULL_AFTER:
            return
        self._pulling = True

        def run():
            try:
                conn = open_db(mode_db_path(""))
                with self.lock:
                    team.pull(conn, utc_now())
                conn.close()
            finally:
                self._pulling = False
        threading.Thread(target=run, daemon=True).start()

    def reset_practice(self) -> None:
        for c in getattr(self._local, "conns", {}).values():  # practice = main data now + hypothetical cases; reset = rebuild
            c.close()
        self._local.conns = {}
        build_practice()


class Handler(BaseHTTPRequestHandler):
    app: App
    server_version = f"personal-board/{VERSION}"

    def log_message(self, fmt, *args):
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _html(self, name: str, mode: str, **inject) -> None:
        inject.setdefault("BASE", f"/{mode}" if mode else "")
        inject.setdefault("MODE", mode)
        self._send(200, render(name, **inject).encode("utf-8"), "text/html; charset=utf-8")

    @staticmethod
    def _split(path: str) -> tuple[str, str]:
        """'/sample/goal/E1' → ('sample', '/goal/E1'); '/' → ('', '/')."""
        for mode in ("sample", "practice"):
            if path == f"/{mode}" or path.startswith(f"/{mode}/"):
                return mode, path[len(mode) + 1:] or "/"
        return "", path

    def do_GET(self) -> None:
        u = urlsplit(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        mode, path = self._split(u.path)
        try:
            if path.startswith("/static/"):
                p = (STATIC / path[len("/static/"):]).resolve()
                if not p.is_file() or STATIC not in p.parents:
                    raise KeyError(path)
                return self._send(200, p.read_bytes(), mimetypes.guess_type(str(p))[0] or "application/octet-stream")
            conn = self.app.conn(mode)
            if mode == "" and path in ("/", "/api/state"):
                self.app.maybe_pull()
            if path == "/":
                day = date.fromisoformat(q["day"]) if q.get("day") else local_day(utc_now())
                self._html("index.html", mode, STATE_JSON=_json_for_html(state(conn, day, mode=mode)))
            elif path.startswith("/goal/"):
                self._html("goal.html", mode, DETAIL_JSON=_json_for_html(goal_detail(conn, path[len("/goal/"):])),
                           MODE_LABEL=t(f"mode.suffix.{mode}") if mode else "")
            elif path == "/guide":
                self._html("guide.html", mode)
            elif path == "/healthz":
                self._json({"ok": True, "service": "personal-board", "modes": list(MODES), "practice": False})
            elif path == "/api/state":
                day = date.fromisoformat(q["day"]) if q.get("day") else local_day(utc_now())
                self._json(state(conn, day, mode=mode))
            elif path == "/api/days":
                self._json(day_counts(conn, date.fromisoformat(q["from"]), date.fromisoformat(q["to"])))
            elif path == "/api/timeline":
                self._json(timeline(conn, parse_ts(q["from"]), parse_ts(q["to"])))
            elif path == "/api/pending":
                self._json({"entries": pending_entries(conn)})
            elif path == "/api/actions":
                self._json({"actions": action_specs(), "values": values()})
            else:
                raise KeyError(path)
        except KeyError as e:
            self._send(404, t("http.no_page", path=e).encode("utf-8"), "text/plain; charset=utf-8")
        except ValueError as e:
            self._json({"ok": False, "error": t("http.bad_params", error=e)}, 400)

    def do_POST(self) -> None:
        u = urlsplit(self.path)
        mode, path = self._split(u.path)
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return self._json({"ok": False, "error": t("http.bad_length")}, 400)
        raw = self.rfile.read(n) if n else b""
        try:
            body = json.loads(raw.decode("utf-8")) if raw else {}
        except ValueError:
            return self._json({"ok": False, "error": t("http.not_json")}, 400)
        if path == "/api/act":
            if mode == "sample":
                return self._json({"ok": False, "error": t("http.sample_readonly")}, 403)
            if not isinstance(body, dict) or "action" not in body or not isinstance(body.get("params", {}), dict):
                return self._json({"ok": False, "error": t("http.act_format")}, 400)
            try:
                with self.app.lock:
                    r = apply_action(self.app.conn(mode), str(body["action"]), body.get("params", {}), utc_now())
            except ActionError as e:
                return self._json({"ok": False, "error": e.message}, 400)
            except (ValueError, TypeError) as e:
                return self._json({"ok": False, "error": t("http.bad_params", error=e)}, 400)
            return self._json(r.as_dict())
        if path == "/api/pull":
            if mode:
                return self._json({"ok": False, "error": t("http.mode_no_pull")}, 403)
            if not settings.team_enabled():
                return self._json({"ok": False, "error": t("team.off")}, 409)
            with self.app.lock:
                r = team.pull(self.app.conn(""), utc_now())
            return self._json(r, 200 if r["ok"] else 502)
        if path == "/api/reset":
            if mode != "practice":
                return self._json({"ok": False, "error": t("http.reset_practice_only")}, 403)
            with self.app.lock:
                self.app.reset_practice()
            return self._json({"ok": True})
        self._send(404, t("http.no_api").encode("utf-8"), "text/plain; charset=utf-8")


def make_server(cfg: dict, port: int) -> ThreadingHTTPServer:
    app = App(cfg)
    handler = type("BoundHandler", (Handler,), {"app": app})
    return ThreadingHTTPServer(("127.0.0.1", port), handler)


def serve(cfg: dict, port: int) -> None:
    srv = make_server(cfg, port)
    print(t("cli.serving", port=port), flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
