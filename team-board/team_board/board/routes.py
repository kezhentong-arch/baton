"""看板的页面与接口。写操作一律走 actions.apply_action。"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from urllib.parse import parse_qsl, urlencode, urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool

from team_board.auth import Actor, get_actor
from team_board.board.actions import ActionError, Who, action_specs, apply_action
from team_board.board.github_sync import make_post, resolve_token, start_background_sync
from team_board.board.issues import GhData
from team_board.board.model import (DEFAULT_ZOOM, is_team_owner, iso, lines, pause_kinds, people, repos, stages,
                                    status_label, tz, tz_note, tz_text, utc_now)
from team_board.board.state import fold, resolve
from team_board.board.store import build_practice, get_board_db, is_practice, load_events, practice_reset_at
from team_board.board.timeline import version_done_at, version_name
from team_board.board.view import (blockers, build_goal, build_index, build_version, freshness, goal_summary,
                                   note_rows)
from team_board.i18n import t
from team_board.templating import make_templates, page_ctx

router = APIRouter()
templates = make_templates()


def _who(request: Request, actor: Actor) -> Who:
    return Who(actor.person, actor.via)


def _me(request: Request, who: Who) -> dict:
    p = request.app.state.cfg.person(who.person)
    return {"id": p.id, "name": p.name, "role": p.role, "letter": p.letter}


def _safe_next(n: str) -> str:
    return n if n.startswith("/board") and "//" not in n and "\n" not in n else "/board"


def _back(nxt: str, **msg: str) -> RedirectResponse:
    parts = urlsplit(nxt)
    q = [(k, v) for k, v in parse_qsl(parts.query) if k not in ("ok", "err")]
    q += [(k, v) for k, v in msg.items() if v]
    return RedirectResponse(f"{parts.path}?{urlencode(q)}" if q else parts.path, status_code=303)


def _root(request: Request) -> str:
    """页面与接口的路径前缀：正式 /board，练手 /board/practice（练手看板的数据完全隔离）。"""
    return "/board/practice" if is_practice(request) else "/board"


def _common(request: Request, who: Who) -> dict:
    cfg = request.app.state.cfg
    practice = is_practice(request)
    return {"who": who, "is_team_owner": is_team_owner(who.person), "people": people(), "lines": lines(),
            "person_colors": cfg.person_colors, "stage_colors": cfg.stage_colors,
            "stages": stages(), "pause_kinds": pause_kinds(), "repos": repos(),
            "github_on": cfg.github.enabled, "tz": tz_note(),
            "practice": practice, "root": _root(request),
            "api_root": "/api/board/practice" if practice else "/api/board"}


def _index(request: Request, actor: Actor, conn: sqlite3.Connection, *, sample: bool, line: str,
           person: str, active: str, zoom: str, err: str, ok: str) -> HTMLResponse:
    who = _who(request, actor)
    v = build_index(conn, utc_now(), line=line, person=person, active_only=active == "1",
                    zoom=zoom, sample=sample, root=_root(request))
    reset_at = practice_reset_at(conn) if is_practice(request) else None
    return templates.TemplateResponse(request, "board/index.html", page_ctx(
        # 筛选条件用校验过的（不认识的人 / 线已在 build_index 里换成「全部」并给了提示）
        request, actor, v=v, err=err, ok=ok, f_line=v["line"], f_person=v["person"], f_active=active,
        practice_reset=tz_text(reset_at) if reset_at else "",
        sample_page=sample, **_common(request, who)))


@router.get("/board", response_class=HTMLResponse)
@router.get("/board/practice", response_class=HTMLResponse)
def board_index(request: Request, line: str = "", person: str = "", active: str = "",
                zoom: str = DEFAULT_ZOOM, err: str = "", ok: str = "",
                actor: Actor = Depends(get_actor),
                conn: sqlite3.Connection = Depends(get_board_db)) -> HTMLResponse:
    return _index(request, actor, conn, sample=False, line=line, person=person, active=active,
                  zoom=zoom, err=err, ok=ok)


@router.get("/board/sample", response_class=HTMLResponse)
def board_sample(request: Request, line: str = "", person: str = "", active: str = "",
                 zoom: str = DEFAULT_ZOOM, err: str = "", ok: str = "",
                 actor: Actor = Depends(get_actor),
                 conn: sqlite3.Connection = Depends(get_board_db)) -> HTMLResponse:
    """示例看板：和真实看板同一套页面、同样的线，真实目标照常显示，另加标了「示例」的假设案例。"""
    return _index(request, actor, conn, sample=True, line=line, person=person, active=active,
                  zoom=zoom, err=err, ok=ok)


@router.get("/board/goal/{goal_id}", response_class=HTMLResponse)
@router.get("/board/practice/goal/{goal_id}", response_class=HTMLResponse)
def board_goal(request: Request, goal_id: int, err: str = "", ok: str = "",
               actor: Actor = Depends(get_actor),
               conn: sqlite3.Connection = Depends(get_board_db)) -> HTMLResponse:
    who = _who(request, actor)
    b = fold(load_events(conn))
    g = b.goals.get(goal_id)
    if g is None:
        raise HTTPException(404, t("err.goal_page_missing"))
    d = build_goal(conn, b, g, utc_now(), who, root=_root(request))
    return templates.TemplateResponse(request, "board/goal.html", page_ctx(
        request, actor, d=d, err=err, ok=ok, **_common(request, who)))


@router.get("/board/version", response_class=HTMLResponse)
@router.get("/board/practice/version", response_class=HTMLResponse)
def board_version(request: Request, repo: str, number: int, err: str = "", ok: str = "",
                  actor: Actor = Depends(get_actor),
                  conn: sqlite3.Connection = Depends(get_board_db)) -> HTMLResponse:
    who = _who(request, actor)
    if repo not in repos():
        raise HTTPException(404, t("err.no_repo"))
    d = build_version(conn, fold(load_events(conn)), repo, number, utc_now())
    return templates.TemplateResponse(request, "board/version.html", page_ctx(
        request, actor, d=d, err=err, ok=ok, **_common(request, who)))


@router.post("/board/practice/reset")
def board_practice_reset(request: Request, actor: Actor = Depends(get_actor)) -> RedirectResponse:
    """练手数据重置 = 重新复制此刻的正式数据。"""
    _who(request, actor)
    build_practice(request.app.state.cfg.data_dir)
    return _back("/board/practice", ok=t("msg.practice_reset"))


@router.post("/board/act")
@router.post("/board/practice/act")
async def board_act_form(request: Request, actor: Actor = Depends(get_actor),
                         conn: sqlite3.Connection = Depends(get_board_db)) -> RedirectResponse:
    who = _who(request, actor)
    form = await request.form()
    action = str(form.get("action", ""))
    nxt = _safe_next(str(form.get("next", "/board")))
    params = {k: str(v) for k, v in form.items()
              if k not in ("action", "next", "occurred_at_local") and str(v).strip() != ""}
    occ_local = str(form.get("occurred_at_local", "")).strip()
    if occ_local:
        try:
            params["occurred_at"] = iso(datetime.fromisoformat(occ_local).replace(tzinfo=tz()))
        except ValueError:
            return _back(nxt, err=t("err.backfill_time"))
    try:
        # 放进线程池：后台同步占着库时这里会等锁，不能卡住整个站的事件循环
        await run_in_threadpool(apply_action, conn, action, params, who, utc_now())
    except ActionError as e:
        return _back(nxt, err=e.message)
    return _back(nxt, ok=t("msg.saved"))


@router.post("/api/board/act")
@router.post("/api/board/practice/act")
async def board_act_api(request: Request, actor: Actor = Depends(get_actor),
                        conn: sqlite3.Connection = Depends(get_board_db)) -> JSONResponse:
    who = _who(request, actor)
    try:
        body = await request.json()
    except ValueError:
        return JSONResponse({"ok": False, "error": t("err.body_not_json")}, status_code=400)
    if not isinstance(body, dict) or set(body) - {"action", "params"} \
            or not isinstance(body.get("params", {}), dict):
        return JSONResponse({"ok": False, "error": t("err.body_shape")}, status_code=400)
    try:
        r = await run_in_threadpool(apply_action, conn, str(body.get("action", "")),
                                    body.get("params", {}), who, utc_now())
    except ActionError as e:
        return JSONResponse({"ok": False, "error": e.message}, status_code=e.status)
    return JSONResponse({"ok": True, "event_ids": r.event_ids, "goal_id": r.goal_id})


def _sync_now(request: Request) -> tuple[bool, str]:
    cfg = request.app.state.cfg
    if not cfg.github.enabled:
        return False, t("err.github_off")
    token = resolve_token(os.environ, cfg)
    if not token:
        return False, t("sync.no_token", env=cfg.github.token_env)
    if not start_background_sync(cfg.data_dir, make_post(token)):
        return True, t("sync.already_running")
    return True, t("sync.started")


@router.post("/board/sync")
def board_sync_form(request: Request, actor: Actor = Depends(get_actor)) -> RedirectResponse:
    _who(request, actor)
    ok, msg = _sync_now(request)
    return _back("/board", **({"ok": msg} if ok else {"err": msg}))


@router.post("/api/board/sync")
def board_sync_api(request: Request, actor: Actor = Depends(get_actor)) -> JSONResponse:
    _who(request, actor)
    ok, msg = _sync_now(request)
    return JSONResponse({"ok": ok, "message": msg}, status_code=200 if ok else 502)


def _zones(request: Request) -> dict:
    cfg = request.app.state.cfg
    return {"timezone": {"name": cfg.zone.name, "label": cfg.zone.label},
            "second_timezone": ({"name": cfg.zone2.name, "label": cfg.zone2.label} if cfg.zone2 else None)}


@router.get("/api/board/actions")
def board_actions_api(request: Request, actor: Actor = Depends(get_actor)) -> dict:
    """操作说明：每个操作做什么、谁能做、必填和选填字段（MCP / 命令行据此追问缺的信息）。"""
    who = _who(request, actor)
    cfg = request.app.state.cfg
    return {"actions": action_specs(),
            "common_optional": {"occurred_at": t("act.occurred_at")},
            "values": {"line": list(lines()), "stage": list(stages()), "people": people(),
                       "roles": {p.id: p.role for p in cfg.persons},
                       "source_letters": dict(cfg.letters),
                       "pause_kind": pause_kinds(), "repo": list(repos()),
                       "link_kind": {"link": t("link.kind.link"), "subcontract": t("link.kind.subcontract")}},
            "me": _me(request, who), "lang": cfg.lang, "title": cfg.title, **_zones(request)}


@router.get("/api/board/resolve")
@router.get("/api/board/practice/resolve")
def board_resolve_api(request: Request, num: str = "", actor: Actor = Depends(get_actor),
                      conn: sqlite3.Connection = Depends(get_board_db)) -> JSONResponse:
    """任意一种号（来源号 A16、永久号 G27、层级号 G2.5）→ 同一个目标和它关联的 GitHub 单
    （提交信息里写的号永远查得到）。查提交的命令拿这里的永久号和来源号去搜提交信息。"""
    _who(request, actor)
    b = fold(load_events(conn))
    g = resolve(b, num)
    if g is None:
        return JSONResponse({"ok": False, "error": t("err.resolve_miss", num=num.strip() or t("err.resolve_empty"))},
                            status_code=404)
    gh = GhData(conn)
    issues = []
    for link in g.links:
        issue = gh.issues.get((link.repo, link.number))
        issues.append({"repo": link.repo, "number": link.number, "kind": link.kind,
                       "title": issue.title if issue else "", "url": issue.url if issue else "",
                       "state": issue.state if issue else ""})
    return JSONResponse({"ok": True, "id": g.id, "gnum": g.gnum, "permanent": g.permanent, "source": g.source,
                         "title": g.title, "line": g.line, "owner": people().get(g.owner, ""), "owner_key": g.owner,
                         "status": status_label(g.status), "sample": g.sample,
                         "practice": is_practice(request), "issues": issues})


@router.get("/api/board/state")
@router.get("/api/board/practice/state")
def board_state_api(request: Request, actor: Actor = Depends(get_actor),
                    conn: sqlite3.Connection = Depends(get_board_db)) -> dict:
    who = _who(request, actor)
    now = utc_now()
    b, gh = fold(load_events(conn)), GhData(conn)

    def done_at(ref: str, vt):
        repo, num = ref.split("#")
        return version_done_at(vt, gh.milestones.get((repo, int(num))))

    return {"now_local": tz_text(now), "sync": freshness(conn, now),
            "me": _me(request, who), **_zones(request),
            "practice": is_practice(request),
            "blockers": [{"kind": x.kind, "text": x.text, "href": x.href} for x in blockers(b, gh, now, root=_root(request))],
            "goals": [goal_summary(g, b, gh, now) for g in sorted(b.goals.values(), key=lambda g: g.id)],
            "versions": {ref: {"baseline": str(vt.baseline or ""), "latest": str(vt.latest or ""),
                               "name": version_name(ref, gh),
                               "done": done_at(ref, vt) is not None,
                               "done_at": iso(done_at(ref, vt)) if done_at(ref, vt) else ""}
                         for ref, vt in b.versions.items()},
            # 口述清单：AI 录入前要知道每条口述是谁写的、关于哪个目标、录过没有
            "notes": note_rows(b, None, limit=50)}
