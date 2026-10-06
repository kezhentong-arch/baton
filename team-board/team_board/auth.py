"""登录与身份：不依赖任何外部服务。

两种模式（配置 auth）：
- local（默认，本地试用）：不用登录，页面右上角选「我是谁」，记在 cookie 里；只允许监听本机回环地址。
- token：每人一个个人令牌（在配置里）。浏览器用令牌登录后记 cookie；AI / 命令行每次请求带
  `Authorization: Bearer <个人令牌>`。身份由令牌决定——没有「拿着共享凭证自报是谁」这回事。

两种模式下带了 Bearer 令牌的请求都按令牌认人，并记为「经 AI」。
"""
from __future__ import annotations

import hmac
from dataclasses import dataclass

from fastapi import HTTPException, Request

from team_board.config import Config, Person
from team_board.i18n import t

COOKIE_SESSION = "tb_session"     # token 模式：登录后存个人令牌（HttpOnly）
COOKIE_PERSON = "tb_person"       # local 模式：选的「我是谁」
COOKIE_MAX_AGE = 60 * 60 * 24 * 30


@dataclass(frozen=True)
class Actor:
    person: str     # 配置里的人的 id
    via: str        # "web" | "ai"


class LoginRequired(Exception):
    """token 模式下没登录：页面跳登录页，接口回 401（见 main.py 的处理）。"""


def person_by_token(cfg: Config, token: str) -> Person | None:
    """逐个做定长比较，不因为前缀对上几位而更快返回。"""
    found = None
    for p in cfg.persons:
        if p.token and hmac.compare_digest(p.token.encode(), token.encode()):
            found = p
    return found


def bearer_token(request: Request) -> str | None:
    raw = request.headers.get("Authorization", "")
    scheme, _, value = raw.partition(" ")
    return value.strip() if scheme.lower() == "bearer" and value.strip() else None


def is_https(request: Request) -> bool:
    """直接 HTTPS，或前面的反向代理说自己收到的是 HTTPS。"""
    proto = request.headers.get("X-Forwarded-Proto", "").split(",")[0].strip().lower()
    return request.url.scheme == "https" or proto == "https"


def get_actor(request: Request) -> Actor:
    cfg: Config = request.app.state.cfg
    token = bearer_token(request)
    if token is not None:
        p = person_by_token(cfg, token)
        if p is None:
            raise HTTPException(401, t("auth.bad_token"))
        return Actor(p.id, "ai")
    if cfg.auth == "local":
        p = cfg.person(request.cookies.get(COOKIE_PERSON, "")) or cfg.default_person
        # 本地试用模式没有令牌也能调接口；脚本想标明「经 AI」就带这个头
        return Actor(p.id, "ai" if request.headers.get("X-Board-Via") == "ai" else "web")
    session = request.cookies.get(COOKIE_SESSION, "")
    p = person_by_token(cfg, session) if session else None
    if p is None:
        raise LoginRequired()
    return Actor(p.id, "web")
