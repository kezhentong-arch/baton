"""模板环境统一出口。

Jinja 默认把未定义变量静默渲染成空串，会掩盖「上下文缺键」这类真实问题——
统一改为 StrictUndefined，缺键当场响亮抛错。界面文字一律走翻译表：模板里用全局函数 t()。
"""
import re
from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates
from jinja2 import StrictUndefined
from markupsafe import Markup, escape

from team_board import i18n
from team_board.auth import Actor

_TEMPLATES_DIR = Path(__file__).parent / "templates"

# 网址只认 http(s) 开头、连续的网址字符；中文与全角标点不在字符集里，「：https://…）」天然断开。
# 末尾的英文句读、多出来的右括号算正文不算网址（「见 https://x.com/a.」）。
_URL = re.compile(r"https?://[A-Za-z0-9\-._~:/?#\[\]@!$&'()*+,;=%]+")
_URL_TAIL = ".,;:!?'\""


def linkify(text: str) -> Markup:
    """正文照旧转义，其中的网址变成新标签页打开的链接。

    「做什么 / 做了什么 / 为什么放弃」里常带文档链接，原样当文字显示点不开。
    只认 http(s)，`javascript:` 这类写法永远不会成链接。
    """
    out, pos = [], 0
    for m in _URL.finditer(text):
        url = m.group(0)
        while url[-1] in _URL_TAIL or (url[-1] == ")" and url.count("(") < url.count(")")):
            url = url[:-1]
        if url.endswith("://"):                                         # 只剩个协议头，不是网址
            continue
        out.append(escape(text[pos:m.start()]))
        out.append(Markup('<a href="{0}" target="_blank" rel="noopener">{0}</a>').format(url))
        pos = m.start() + len(url)                                      # 剥掉的句读留给下一段正文
    out.append(escape(text[pos:]))
    return Markup("").join(out)


def page_ctx(request: Request, actor: Actor, **extra) -> dict:
    """所有整页模板的公共上下文（页头导航 + 右上角「我是谁」）。

    不用 Starlette 的 context_processor：那条路取不到路由已经依赖注入好的 Actor，测试用
    `dependency_overrides[get_actor]` 换掉的身份也看不见。谁渲染页面，谁把手里的 actor 传进来。
    """
    cfg = request.app.state.cfg
    me = cfg.person(actor.person)
    return {
        "title": cfg.title,
        "html_lang": i18n.html_lang(cfg.lang),
        "me": me,
        "me_role": i18n.tr(cfg.lang, f"role.{me.role}"),
        "nav": [("/board", i18n.tr(cfg.lang, "nav.board"), i18n.tr(cfg.lang, "nav.board_tip")),
                ("/board/practice", i18n.tr(cfg.lang, "nav.practice"), i18n.tr(cfg.lang, "nav.practice_tip"))],
        "is_local": cfg.auth == "local",
        "everyone": cfg.persons if cfg.auth == "local" else (),
        **extra,
    }


def make_templates() -> Jinja2Templates:
    templates = Jinja2Templates(directory=_TEMPLATES_DIR)
    templates.env.undefined = StrictUndefined
    templates.env.filters["linkify"] = linkify
    # 页面脚本里的文字原样写出（不转成 \uXXXX），看源码、搜文字都直观
    templates.env.policies["json.dumps_kwargs"] = {"sort_keys": True, "ensure_ascii": False}
    templates.env.globals["t"] = i18n.t
    templates.env.globals["js_strings"] = i18n.js_strings
    return templates
