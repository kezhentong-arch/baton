"""Configuration: one JSON file written by `init`.

Who you are, your lines and stages, your time zone(s), the interface language and the optional
team-board connection all live here. No person, line or stage name is hard-coded anywhere else:
behaviour hangs on the keys and flags of this file (for example a line's `personal: true`).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ENV_DATA = "PERSONAL_BOARD_DATA"          # overrides the data directory
ENV_TEAM_TOKEN = "PERSONAL_BOARD_TEAM_TOKEN"  # overrides team_board.token (keeps the token out of the file)
DEFAULT_DATA_DIR = Path.home() / ".local" / "share" / "personal-board"
DEFAULT_PORT = 10990
DEFAULT_TIMEZONE = "America/Los_Angeles"
LANGS: tuple[str, ...] = ("zh", "en")
# G numbers come from the team board and E numbers mark example goals, so neither can be a birth letter.
RESERVED_LETTERS: tuple[str, ...] = ("G", "E")

LINE_COLORS: tuple[str, ...] = ("#4fa8a0", "#7a86d6", "#b7975f", "#8a97a8", "#c08497", "#6fa8dc")
PERSONAL_COLOR = "#9aa5b1"   # greyer than the team lines so it does not compete with them
STAGE_COLORS: tuple[str, ...] = ("#a88ef2", "#62a9f2", "#f27aa6", "#4fcb8e", "#f3ae55", "#5fc9c9", "#c9a45f")
NO_STAGE_COLOR = "#b8bec8"
MARKS = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"

DEFAULT_NAMES: dict[str, dict] = {
    "zh": {"lines": ["产品", "增长", "运营", "团队协作"], "personal": "个人事项",
           "stages": ["业务", "产品", "UI", "开发", "测试"]},
    "en": {"lines": ["Product", "Growth", "Operations", "Team"], "personal": "Personal",
           "stages": ["Business", "Product", "Design", "Dev", "Test"]},
}


class ConfigError(ValueError):
    pass


def data_dir() -> Path:
    return Path(os.environ.get(ENV_DATA, str(DEFAULT_DATA_DIR))).expanduser()


def config_path() -> Path:
    return data_dir() / "config.json"


def _msg(key: str, lang: str | None, /, **kw) -> str:
    from app.i18n import t
    return t(key, lang=lang if lang in LANGS else "en", **kw)


def zone_label(name: str) -> str:
    """Default display label of an IANA zone: its city part ("America/Los_Angeles" → "Los Angeles")."""
    return name.rsplit("/", 1)[-1].replace("_", " ")


def default_letter(name: str) -> str:
    first = (name or "").strip()[:1].upper()
    return first if "A" <= first <= "Z" and first not in RESERVED_LETTERS else "P"


def default_config(lang: str = "en", *, person_id: str = "me", name: str = "", letter: str = "",
                   port: int = DEFAULT_PORT, timezone: str = DEFAULT_TIMEZONE, timezone_label: str = "",
                   second_timezone: str = "", second_timezone_label: str = "",
                   team_url: str = "", team_token: str = "") -> dict:
    """The config `init` writes. Lines and stages get the default names of the chosen language."""
    names = DEFAULT_NAMES[lang if lang in LANGS else "en"]
    cfg: dict = {
        "lang": lang,
        "person": {"id": person_id, "name": name or person_id, "letter": letter or default_letter(name or person_id)},
        "port": port,
        "timezone": {"name": timezone, "label": timezone_label or zone_label(timezone)},
        "lines": [{"name": n, "color": LINE_COLORS[i % len(LINE_COLORS)]} for i, n in enumerate(names["lines"])]
                 + [{"name": names["personal"], "color": PERSONAL_COLOR, "personal": True}],
        "stages": [{"name": n, "color": STAGE_COLORS[i % len(STAGE_COLORS)]} for i, n in enumerate(names["stages"])],
        "team_board": {"base_url": team_url, "token": team_token},
    }
    if second_timezone:
        cfg["second_timezone"] = {"name": second_timezone, "label": second_timezone_label or zone_label(second_timezone)}
    return cfg


def _zone(raw, lang: str | None, key: str) -> dict | None:
    if raw in (None, "", {}):
        return None
    if isinstance(raw, str):
        raw = {"name": raw}
    name = str(raw.get("name") or "").strip()
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        raise ConfigError(_msg("cfg.bad_zone", lang, key=key, value=name)) from None
    return {"name": name, "label": str(raw.get("label") or "").strip() or zone_label(name)}


def _named(items, colors: tuple[str, ...], lang: str | None, key: str) -> list[dict]:
    out, seen = [], set()
    for i, raw in enumerate(items or []):
        item = {"name": raw} if isinstance(raw, str) else dict(raw)
        name = str(item.get("name") or "").strip()
        if not name or name in seen:
            raise ConfigError(_msg("cfg.bad_names", lang, key=key))
        seen.add(name)
        item["name"] = name
        item["color"] = str(item.get("color") or colors[i % len(colors)])
        if item.get("team_name") in (None, ""):
            item.pop("team_name", None)
        out.append(item)
    if not out:
        raise ConfigError(_msg("cfg.bad_names", lang, key=key))
    return out


def normalize(cfg: dict) -> dict:
    """Validate a config and fill in what may be left out. Raises ConfigError with a plain reason."""
    if not isinstance(cfg, dict):
        raise ConfigError(_msg("cfg.not_object", None))
    lang = cfg.get("lang", "en")
    if lang not in LANGS:
        raise ConfigError(_msg("cfg.bad_lang", None, value=lang))
    person = cfg.get("person")
    if not isinstance(person, dict) or not str(person.get("id") or "").strip():
        raise ConfigError(_msg("cfg.bad_person", lang))
    pid = str(person["id"]).strip()
    letter = str(person.get("letter") or "").strip()
    if len(letter) != 1 or not ("A" <= letter <= "Z") or letter in RESERVED_LETTERS:
        raise ConfigError(_msg("cfg.bad_letter", lang, value=letter))
    try:
        port = int(cfg.get("port", DEFAULT_PORT))
    except (TypeError, ValueError):
        raise ConfigError(_msg("cfg.bad_port", lang)) from None
    main = _zone(cfg.get("timezone") or DEFAULT_TIMEZONE, lang, "timezone")
    second = _zone(cfg.get("second_timezone"), lang, "second_timezone")
    if second and second["name"] == main["name"]:
        second = None
    names = DEFAULT_NAMES[lang]
    lines = _named(cfg["lines"] if "lines" in cfg else names["lines"] + [{"name": names["personal"], "personal": True, "color": PERSONAL_COLOR}],
                   LINE_COLORS, lang, "lines")
    for ln in lines:
        ln["personal"] = bool(ln.get("personal"))
    stages = _named(cfg["stages"] if "stages" in cfg else names["stages"], STAGE_COLORS, lang, "stages")
    tb = cfg.get("team_board") or {}
    if not isinstance(tb, dict):
        raise ConfigError(_msg("cfg.bad_team", lang))
    base = str(tb.get("base_url") or "").strip().rstrip("/")
    if base and not base.startswith(("http://", "https://")):
        raise ConfigError(_msg("cfg.bad_team", lang))
    out = {"lang": lang, "person": {"id": pid, "name": str(person.get("name") or pid).strip(), "letter": letter},
           "port": port, "timezone": main, "lines": lines, "stages": stages,
           "team_board": {"base_url": base, "token": str(tb.get("token") or "").strip(),
                          "owner": str(tb.get("owner") or "").strip()}}
    if second:
        out["second_timezone"] = second
    return out


def load_config() -> dict:
    """Read and validate config.json. A missing file is an error: the board never guesses whose it is."""
    p = config_path()
    if not p.is_file():
        raise FileNotFoundError(_msg("cfg.missing", None, path=p))
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except ValueError as e:
        raise ConfigError(_msg("cfg.not_json", None, path=p, error=e)) from None
    return normalize(raw)


def save_config(cfg: dict) -> Path:
    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return p


# ---------- the active config ----------
# Everything below reads one process-wide config. It is loaded lazily from the data directory;
# `use()` sets it explicitly (the CLI after `init`, tests). Without a config file the English
# defaults apply so library code and tests work on a bare database.
_active: dict | None = None


def active() -> dict:
    global _active
    if _active is None:
        _active = load_config() if config_path().is_file() else normalize(default_config("en"))
    return _active


def use(cfg: dict) -> dict:
    global _active
    _active = normalize(cfg)
    return _active


def reload() -> None:
    global _active
    _active = None


def lang() -> str:
    return active()["lang"]


def person() -> dict:
    return active()["person"]


def lines() -> list[dict]:
    return active()["lines"]


def line_names() -> list[str]:
    return [ln["name"] for ln in lines()]


def team_line_names() -> list[str]:
    return [ln["name"] for ln in lines() if not ln["personal"]]


def is_line(name) -> bool:
    return name in line_names()


def is_team_line(name) -> bool:
    """A line whose goals go to the team board. Personal lines (`personal: true`) never do."""
    return name in team_line_names()


def line_index(name) -> int:
    names = line_names()
    return names.index(name) if name in names else len(names)   # lines dropped from the config sort last


def _steady(name, palette: tuple[str, ...]) -> str:
    """A colour for a name the config does not know (a loaded case pack, a renamed line): always the same one."""
    return palette[sum(ord(c) for c in str(name)) % len(palette)]


def line_mark(name) -> tuple[str, str]:
    """(①, colour) of a line; a line that is not in the config gets a dot and a steady colour."""
    for i, ln in enumerate(lines()):
        if ln["name"] == name:
            return MARKS[i % len(MARKS)], ln["color"]
    return "·", _steady(name, LINE_COLORS)


def line_views(extra=()) -> list[dict]:
    """Lines for the page in config order; `extra` are lines that still have goals but left the config."""
    out = [{"name": ln["name"], "mark": line_mark(ln["name"])[0], "color": ln["color"], "personal": ln["personal"]}
           for ln in lines()]
    for name in extra:
        if not is_line(name) and all(o["name"] != name for o in out):
            out.append({"name": name, "mark": "·", "color": _steady(name, LINE_COLORS), "personal": False})
    return out


def stage_names() -> list[str]:
    return [s["name"] for s in active()["stages"]]


def stage_color(name) -> str:
    for s in active()["stages"]:
        if s["name"] == name:
            return s["color"]
    return _steady(name, STAGE_COLORS)


def stage_colors() -> dict[str, str]:
    return {s["name"]: s["color"] for s in active()["stages"]}


def tz() -> ZoneInfo:
    return ZoneInfo(active()["timezone"]["name"])


def tz_name() -> str:
    return active()["timezone"]["name"]


def tz_label() -> str:
    return active()["timezone"]["label"]


def second_zone() -> dict | None:
    return active().get("second_timezone")


def zones() -> list[dict]:
    """The configured zones, main first: [{"name", "label"}] with one or two items."""
    z = [active()["timezone"]]
    if second_zone():
        z.append(second_zone())
    return z


def label_of_zone(name: str) -> str:
    for z in zones():
        if z["name"] == name:
            return z["label"]
    return zone_label(name)


def team_board() -> dict:
    tb = dict(active()["team_board"])
    tb["token"] = os.environ.get(ENV_TEAM_TOKEN) or tb["token"]
    return tb


def team_enabled() -> bool:
    """No base_url = the team board is switched off entirely: no pulls, no "unpushed" marks, no noise."""
    return bool(active()["team_board"]["base_url"])
