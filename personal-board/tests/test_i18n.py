"""The translation table: both languages carry exactly the same keys and placeholders, and every key the code,
the templates and the page scripts use exists."""
import re
import string
from pathlib import Path

from app import settings
from app.actions import action_specs, values
from app.i18n import LANGS, TABLE, every, js_table, t, weekday
from tests.conftest import make_config

ROOT = Path(__file__).resolve().parents[1]
CJK = re.compile(r"[一-鿿]")


def _fields(text: str) -> set[str]:
    try:
        return {name.split("!")[0].split(".")[0] for _, name, _, _ in string.Formatter().parse(text) if name}
    except ValueError:      # literal braces (the request-format hint): no placeholders
        return set()


def test_both_languages_have_the_same_keys_and_placeholders():
    zh, en = TABLE["zh"], TABLE["en"]
    assert set(zh) == set(en)
    for key in zh:
        assert _fields(zh[key]) == _fields(en[key]), key
    assert not [k for k, v in en.items() if CJK.search(v)], "English entries must not contain Chinese"
    assert len(TABLE["zh"]["weekdays"].split(",")) == len(TABLE["en"]["weekdays"].split(",")) == 7
    assert len(js_table("zh")["cal_wd"].split(",")) == len(js_table("en")["cal_wd"].split(",")) == 7


def test_every_key_used_in_the_code_exists():
    keys = set(TABLE["en"])
    used: set[str] = set()
    for path in [*ROOT.glob("app/*.py"), *ROOT.glob("cli/*.py")]:
        src = path.read_text(encoding="utf-8")
        used |= set(re.findall(r"""\b(?:t|every|_msg)\(\s*["']([a-z0-9_.]+)["']""", src))
    used -= {"sep"} - keys
    for tpl in ROOT.glob("app/templates/*.html"):
        used |= set(re.findall(r"\{\{t:([a-z0-9_.]+)\}\}", tpl.read_text(encoding="utf-8")))
    assert used - keys == set(), sorted(used - keys)
    js_used: set[str] = set()
    for path in [*ROOT.glob("app/static/*.js"), *ROOT.glob("app/templates/*.html")]:
        src = path.read_text(encoding="utf-8")
        js_used |= set(re.findall(r"""\bT\(\s*'([a-z0-9_]+)'""", src))
        for a, b in re.findall(r"""\bT\([^()?]*\?\s*'([a-z0-9_]+)'\s*:\s*'([a-z0-9_]+)'""", src):   # T(cond ? 'a' : 'b', …)
            js_used |= {a, b}
    js_keys = set(js_table("en"))
    assert js_used - js_keys == set(), sorted(js_used - js_keys)
    # dynamic families: every kind, sync state, action, team status and mode has its entry
    from app.model import ENTRY_KINDS, SYNC_STATES
    for name in [*(f"kind.{k}" for k in ENTRY_KINDS), *(f"sync.{k}" for k in SYNC_STATES), *(f"act.{a}" for a in action_specs()),
                 *(f"team.status.{k}" for k in ("active", "done", "abandoned")), "mode.suffix.sample", "mode.suffix.practice",
                 "occ.upcoming", "occ.cancelled", "label.what", "label.done_what"]:
        assert name in keys, name


def test_no_interface_text_outside_the_table():
    """Templates and page scripts carry no Chinese of their own, and Python modules other than the Chinese string
    table and the demo story carry none either."""
    for path in [*ROOT.glob("app/templates/*.html"), *ROOT.glob("app/static/*.js"), *ROOT.glob("app/static/*.css")]:
        text = path.read_text(encoding="utf-8").replace('"PingFang SC"', "")
        assert not CJK.search(text), (path.name, CJK.findall(text)[:10])
    for path in [*ROOT.glob("app/*.py"), *ROOT.glob("cli/*.py")]:
        if path.name in ("strings_zh.py", "seed.py", "settings.py"):   # the table, the demo story, the default zh line / stage names
            continue
        text = path.read_text(encoding="utf-8").replace('replace("，", ",")', "")   # accepting a full-width comma in id lists is input handling
        assert not CJK.search(text), (path.name, CJK.findall(text)[:10])


def test_reference_and_values_follow_lang():
    settings.use(make_config("zh"))
    assert t("kind.start") == "开工" and weekday(0) == "周一" and "出生号" in action_specs()["goal_create"]["what"]
    assert values()["kind"]["wrap"] == "收尾" and values()["sync_status"] == {"pushed": "已推", "skip": "不推"}
    settings.use(make_config("en"))
    assert t("kind.start") == "Start" and weekday(0) == "Mon"
    ref = action_specs()
    assert all(not CJK.search(spec["what"]) for spec in ref.values())
    assert "(LA)" in ref["goal_create"]["what"]                      # the due hint names the configured main zone
    assert values()["sync_status"] == {"pushed": "Pushed", "skip": "Not pushed"} and values()["repeat"]["monthly"].startswith("Same day")
    assert every("abandon.default") == ["放弃", "Abandoned"]
    assert t("kind.start", lang="zh") == "开工"
