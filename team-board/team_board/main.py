"""应用入口：`create_app(cfg)`。打开就是看板。

    python3 -m team_board start          # 按配置起服务
"""
import asyncio
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from team_board import config as config_mod
from team_board import i18n
from team_board.auth import (COOKIE_MAX_AGE, COOKIE_PERSON, COOKIE_SESSION, LoginRequired, is_https,
                             person_by_token)
from team_board.config import Config, load_config


class _UseConfig:
    """每个请求进来先把「当前配置 / 当前语言」设成这个应用的（纯 ASGI 中间件，路由和线程池里都读得到）。"""

    def __init__(self, app, cfg: Config):
        self.app, self.cfg = app, cfg

    async def __call__(self, scope, receive, send):
        tokens = config_mod.activate(self.cfg)
        try:
            await self.app(scope, receive, send)
        finally:
            config_mod.deactivate(tokens)


def _safe_next(n: str) -> str:
    return n if n.startswith("/board") and "//" not in n and "\n" not in n else "/board"


def create_app(cfg: Config | None = None, *, background: bool = False) -> FastAPI:
    """background=True（`start` 命令）时带后台循环：每日备份，开了自动同步就同步 GitHub。"""
    cfg = cfg or load_config()
    config_mod.use(cfg)
    cfg.data_dir.mkdir(parents=True, exist_ok=True)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        task = None
        if background:
            from team_board.board.github_sync import background_loop
            task = asyncio.create_task(background_loop(cfg))
        yield
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    app = FastAPI(title=cfg.title, docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.cfg = cfg
    app.add_middleware(_UseConfig, cfg=cfg)

    from team_board.board.routes import router as board_router
    from team_board.board.routes import templates

    @app.middleware("http")
    async def add_noindex(request: Request, call_next):
        resp = await call_next(request)
        resp.headers["X-Robots-Tag"] = "noindex, nofollow"
        return resp

    @app.exception_handler(LoginRequired)
    async def login_required(request: Request, exc: LoginRequired):
        if request.url.path.startswith("/api/"):
            return JSONResponse({"ok": False, "error": i18n.tr(cfg.lang, "auth.api_login")}, status_code=401)
        nxt = request.url.path + (f"?{request.url.query}" if request.url.query else "")
        return RedirectResponse(f"/login?next={_safe_next(nxt)}", status_code=303)

    @app.get("/healthz")
    def healthz() -> JSONResponse:
        return JSONResponse({"ok": True})

    @app.get("/")
    def home() -> RedirectResponse:
        return RedirectResponse("/board", status_code=307)

    def _login_page(request: Request, nxt: str, err: str = "", status: int = 200) -> HTMLResponse:
        return templates.TemplateResponse(request, "login.html", {
            "title": cfg.title, "html_lang": i18n.html_lang(cfg.lang), "next": _safe_next(nxt), "err": err},
            status_code=status)

    @app.get("/login", response_class=HTMLResponse)
    def login_form(request: Request, next: str = "/board"):
        if cfg.auth == "local":
            return RedirectResponse("/board", status_code=303)
        return _login_page(request, next)

    @app.post("/login")
    async def login(request: Request):
        if cfg.auth == "local":
            return RedirectResponse("/board", status_code=303)
        form = await request.form()
        token, nxt = str(form.get("token", "")).strip(), str(form.get("next", "/board"))
        if not token or person_by_token(cfg, token) is None:
            return _login_page(request, nxt, i18n.tr(cfg.lang, "auth.bad_token"), 401)
        resp = RedirectResponse(_safe_next(nxt), status_code=303)
        # HttpOnly：页面脚本读不到；SameSite=Lax：别的站发起的表单提交不带它；HTTPS 下加 Secure
        resp.set_cookie(COOKIE_SESSION, token, max_age=COOKIE_MAX_AGE, httponly=True, samesite="lax",
                        secure=is_https(request), path="/")
        return resp

    @app.post("/logout")
    def logout() -> RedirectResponse:
        resp = RedirectResponse("/login" if cfg.auth == "token" else "/board", status_code=303)
        resp.delete_cookie(COOKIE_SESSION, path="/")
        return resp

    @app.post("/whoami")
    async def whoami(request: Request):
        """本地试用模式：选「我是谁」。令牌模式下没有这个入口（身份只由令牌决定）。"""
        if cfg.auth != "local":
            return JSONResponse({"ok": False, "error": i18n.tr(cfg.lang, "auth.local_only")}, status_code=404)
        form = await request.form()
        person = cfg.person(str(form.get("person", "")))
        resp = RedirectResponse(_safe_next(str(form.get("next", "/board"))), status_code=303)
        if person is not None:
            resp.set_cookie(COOKIE_PERSON, person.id, max_age=COOKIE_MAX_AGE, httponly=True, samesite="lax",
                            secure=is_https(request), path="/")
        return resp

    app.include_router(board_router)
    return app
