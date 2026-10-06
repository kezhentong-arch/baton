"""The translation table. Every piece of interface text — templates, page scripts, text assembled in Python,
error messages, MCP tool descriptions, the action reference — goes through here.

    t("err.no_goal", key="G9", example="A19")   # in the configured language
    t("kind.start", lang="zh")                  # in a given language
    every("abandon.default")                    # the text in every language (to recognise text stored earlier)
    js_table()                                  # the "js.*" entries, shipped to the browser as window.__I18N__

Entries under "js." are formatted in the browser (`T(key, {name: value})`); all others with str.format.
tests/test_i18n.py checks that both languages have exactly the same keys and that every key used in the
code exists.
"""
from __future__ import annotations

from app.strings_en import EN
from app.strings_zh import ZH

LANGS: tuple[str, ...] = ("zh", "en")
TABLE: dict[str, dict[str, str]] = {"zh": ZH, "en": EN}


def _lang(lang: str | None) -> str:
    if lang in TABLE:
        return lang
    from app import settings
    return settings.lang()


def t(key: str, /, lang: str | None = None, **kw) -> str:   # positional-only: a template may have a {key} field
    text = TABLE[_lang(lang)][key]
    return text.format(**kw) if kw else text


def every(key: str, /, **kw) -> list[str]:
    """The text of a key in every language, e.g. to recognise something stored while another language was set."""
    return [t(key, lang=lang, **kw) for lang in LANGS]


def weekday(i: int, lang: str | None = None) -> str:
    """Short weekday name, Monday = 0."""
    return TABLE[_lang(lang)]["weekdays"].split(",")[i]


def js_table(lang: str | None = None) -> dict[str, str]:
    return {k[3:]: v for k, v in TABLE[_lang(lang)].items() if k.startswith("js.")}
