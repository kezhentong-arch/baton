"""Case packs: export a whole board as one JSON file and load it into an empty board somewhere else.

A pack lets someone open another person's board as a worked example on their own computer. It is offline
by design: loading never contacts a team board and recognises no particular person — goals, entries and
to-dos are carried over as they are; dictations (private drafts) are left out. Every "unpushed" entry in a
pack becomes "not pushed": they are someone else's entries and must never be pushed from this machine.

Pack format (`format: 1`):

    {"format": 1, "lang": "en", "person": {"id", "name", "letter"}, "exported_at": "<ISO>",
     "config": {"lines": [...], "stages": [...], "timezone": {...}, "second_timezone": {...}},   # optional
     "zone_aliases": {"<label>": "<IANA name>"},                                                 # optional
     "tables": {"goals": [...], "entries": [...], "todos": [...]}}

Rows are table rows keyed by column name. Columns the tables do not have are ignored. `point_zone` must be
an IANA zone name; any other value is looked up in `zone_aliases` and otherwise replaced by the loader's
main time zone. Only `format` and `tables` are required: `person` may be a plain string, and `lang`, `config`
and `zone_aliases` may be absent. Line and stage names missing from the loader's config still display (each
in a steady colour of its own, lines after the configured ones); `adopt_config` copies the pack's lines and
stages into the config instead.
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app import settings
from app.i18n import t
from app.model import iso, zoned
from app.store import get_meta, set_meta

FORMAT = 1
TABLES = ("goals", "entries", "todos")  # notes (the dictation box) are private drafts and stay out of a pack
# Column names used by packs written before the team-board terms were settled.
RENAMED = {"goals": {"company_id": "team_id"}, "entries": {"company_ref": "team_ref"}}
SOURCES = {"company": "team"}


def _rows(conn: sqlite3.Connection, table: str) -> list[dict]:
    return [dict(r) for r in conn.execute(f"SELECT * FROM {table} ORDER BY id")]


def export_case(conn: sqlite3.Connection, now: datetime) -> dict:
    """Main database → a plain-data pack that loads on anyone's machine."""
    cfg = settings.active()
    me = dict(cfg["person"])
    me["id"] = get_meta(conn, "person") or me["id"]
    conf = {"lines": cfg["lines"], "stages": cfg["stages"], "timezone": cfg["timezone"]}
    if cfg.get("second_timezone"):
        conf["second_timezone"] = cfg["second_timezone"]
    return {"format": FORMAT, "lang": cfg["lang"], "person": me, "exported_at": iso(now), "config": conf,
            "tables": {tb: _rows(conn, tb) for tb in TABLES}}


def write_case(conn: sqlite3.Connection, now: datetime, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(export_case(conn, now), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return out


def load_case_file(path: Path) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ValueError(t("case.unreadable", path=path, error=e)) from None


def check_case(data) -> None:
    if not isinstance(data, dict) or data.get("format") != FORMAT or not isinstance(data.get("tables"), dict):
        raise ValueError(t("case.bad_format"))


def case_person(data: dict) -> str:
    """Whose board the pack is: the name in the pack (a pack may also carry just an id string)."""
    who = data.get("person")
    if isinstance(who, dict):
        return str(who.get("name") or who.get("id") or "")
    return str(who or "")


def case_label(data: dict) -> str:
    who = case_person(data) or t("case.someone")
    try:
        at = zoned(datetime.fromisoformat(str(data["exported_at"]).replace("Z", "+00:00")), settings.zones()[0])
    except (KeyError, ValueError):
        return t("case.label_undated", who=who)
    return t("case.label", who=who, at=at)


def missing_names(data: dict) -> dict[str, list[str]]:
    """Line and stage names the pack uses that the active config does not have."""
    goals, entries = data["tables"].get("goals", []), data["tables"].get("entries", [])
    lines = sorted({g.get("line") for g in goals if g.get("line") and not settings.is_line(g.get("line"))})
    stages = sorted({e.get("stage") for e in entries if e.get("stage") and e.get("stage") not in settings.stage_names()})
    return {"lines": lines, "stages": stages}


def _ordered(used: list[str], kind: str) -> list[str]:
    """Names in the order of a language's defaults when they all belong to it, else in order of first appearance."""
    for names in settings.DEFAULT_NAMES.values():
        known = names[kind] + ([names["personal"]] if kind == "lines" else [])
        if used and set(used) <= set(known):
            return [n for n in known if n in used]
    return used


def derived_config(data: dict) -> dict:
    """For a pack without a `config` block: its lines and stages as the data uses them. The loader's own personal
    lines are kept, so there is still a place for private goals."""
    check_case(data)
    lines = list(dict.fromkeys(g["line"] for g in data["tables"].get("goals") or [] if g.get("line")))
    stages = list(dict.fromkeys(e["stage"] for e in data["tables"].get("entries") or [] if e.get("stage")))
    if not lines or not stages:
        raise ValueError(t("case.no_config"))
    mine = [ln for ln in settings.lines() if ln["personal"] and ln["name"] not in lines]
    return {"lines": [{"name": n} for n in _ordered(lines, "lines")] + mine, "stages": _ordered(stages, "stages")}


def adopt_config(data: dict) -> dict:
    """Copy the pack's lines and stages into the config file (person, port, zones and team board stay yours)."""
    conf = data.get("config") or {}
    if not conf.get("lines") or not conf.get("stages"):
        conf = derived_config(data)
    cfg = dict(settings.active())
    cfg["lines"], cfg["stages"] = conf["lines"], conf["stages"]
    cfg = settings.normalize(cfg)
    settings.save_config(cfg)
    return settings.use(cfg)


def _zone(value, aliases: dict) -> str | None:
    if value in (None, ""):
        return None
    name = aliases.get(value, value)
    try:
        ZoneInfo(str(name))
        return str(name)
    except Exception:  # noqa: BLE001 — not an IANA name: the loader's main zone keeps the board readable
        return settings.tz_name()


def import_case(conn: sqlite3.Connection, data: dict, now: datetime) -> dict:
    """Empty database ← pack. Ids are kept (entries point at goals by goal_id). A database that already holds
    goals, entries or to-dos is refused — a pack is never mixed into real data."""
    check_case(data)
    for tb in TABLES:
        if conn.execute(f"SELECT COUNT(*) FROM {tb}").fetchone()[0]:
            raise ValueError(t("case.not_empty"))
    aliases = data.get("zone_aliases") or {}
    try:
        return _import(conn, data, aliases, now)
    except sqlite3.Error as e:   # a row the tables cannot take: nothing is written (one transaction), and the reason is plain
        raise ValueError(t("case.bad_rows", error=e)) from None


def _import(conn: sqlite3.Connection, data: dict, aliases: dict, now: datetime) -> dict:
    counts: dict[str, int] = {}
    with conn:
        for tb in TABLES:
            info = list(conn.execute(f"PRAGMA table_info({tb})"))
            known = {c["name"] for c in info}
            required = {c["name"] for c in info if c["notnull"]}
            rows = data["tables"].get(tb) or []
            for raw in rows:
                r = {RENAMED.get(tb, {}).get(k, k): v for k, v in raw.items()}
                # unknown columns are dropped; a null in a column that must have a value falls back to the column's default
                r = {k: v for k, v in r.items() if k in known and not (v is None and k in required)}
                if tb == "goals":
                    r["source"] = SOURCES.get(r.get("source"), r.get("source") or "local")
                    if r.get("point_at"):
                        r["point_zone"] = _zone(r.get("point_zone"), aliases) or settings.tz_name()
                if tb == "entries" and r.get("sync") == "pending":  # someone else's unpushed entries are "not pushed" here
                    r = dict(r, sync="skip", synced_at=iso(now), team_ref=t("case.no_push"))
                cols = list(r)
                conn.execute(f"INSERT INTO {tb}({', '.join(cols)}) VALUES({', '.join('?' * len(cols))})", [r[c] for c in cols])
            counts[tb] = len(rows)
        _fill_baseline(conn)
        set_meta(conn, "case", case_label(data))
    return counts


_DATE = re.compile(r"\d{4}-\d\d-\d\d(?: \d\d:\d\d)?")


def _fill_baseline(conn: sqlite3.Connection) -> None:
    """Older packs do not carry `baseline_due` (the first plan ever set, which delay is measured from). Recover it
    from the goal's first "plan changed" entry — "old → new" lists the old plan first, any other wording lists
    it last — and fall back to the current plan."""
    for g in conn.execute("SELECT id, due FROM goals WHERE baseline_due IS NULL").fetchall():
        first = conn.execute("SELECT text FROM entries WHERE goal_id=? AND kind='due' ORDER BY id LIMIT 1", (g["id"],)).fetchone()
        dates = _DATE.findall(first["text"]) if first else []
        base = (dates[0] if "→" in first["text"] else dates[-1]) if dates else g["due"]
        if base:
            conn.execute("UPDATE goals SET baseline_due=? WHERE id=?", (base, g["id"]))
