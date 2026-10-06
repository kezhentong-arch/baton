"""Point tasks: things done once at a moment in time (e.g. paying contractors on the 1st of each month).

- One task is one row under its line. It is never pushed to the team board. The row shows one big dot
  per occurrence and no stage bars.
- Hollow = not done yet; ticking it makes it solid.
- A dot appears only when the visible window covers its moment.
- Overdue follows the same rule as goals: the dot stays until today with a red run from its moment to
  now ("overdue N days") until it is done; a late tick draws the red run up to the tick
  ("finished N days overdue").
- Monthly repeat: "day D at HH:MM every month"; any future month shows its hollow dot.

Storage: the goal row carries point_at (first moment), point_zone (the IANA zone whose wall clock rules)
and point_repeat (monthly or empty). Each tick is an entry of kind point_done whose `occurrence` is that
moment (UTC ISO); voiding it makes the dot hollow again. Monthly moments are computed on the fly from
the wall clock of point_zone — "the 1st at 10:00 in Tokyo" stays 10:00 in Tokyo when another zone
switches daylight saving, which adding a fixed interval would get wrong by an hour.
"""
from __future__ import annotations

import calendar
import re
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from app import settings
from app.i18n import every, t
from app.model import iso, parse_ts

REPEATS: tuple[str, ...] = ("monthly",)
EARLY_LIMIT = timedelta(days=7)   # with no occurrence named, the earliest undone one must be within 7 days
#                                   (ticking a few days early is common; earlier is probably a slip — ask)

_LOCAL = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})[ T](\d{1,2}):(\d{2})$")


def zone_values() -> dict[str, str]:
    """The accepted point_zone values and their labels: the configured zones, main first."""
    return {z["name"]: z["label"] for z in settings.zones()}


def parse_zone(raw) -> str:
    """→ IANA name. Accepts nothing (main zone), "main" / "second", or a configured zone's name or label."""
    s = str(raw or "").strip()
    zs = settings.zones()
    if s in ("", "main"):
        return zs[0]["name"]
    if s == "second" and len(zs) > 1:
        return zs[1]["name"]
    for z in zs:
        if s.lower() in (z["name"].lower(), z["label"].lower()):
            return z["name"]
    raise ValueError(t("point.bad_zone", options=t("sep").join(f"{z['name']}{t('paren', x=z['label'])}" for z in zs),
                       value=repr(raw)))


def parse_repeat(raw) -> str | None:
    s = str(raw or "").strip()
    if s in ("", "none") or s in every("point.repeat_none"):
        return None
    if s in REPEATS or s in every("point.repeat_monthly"):
        return "monthly"
    raise ValueError(t("point.bad_repeat", value=repr(raw)))


def parse_point_at(raw, zone: str) -> datetime:
    """"2026-11-01 10:00" is read on the wall clock of `zone`; an ISO string with an offset is accepted too.
    A bare date is rejected: a moment goes down to the minute (pick one even if the hour does not matter)."""
    s = str(raw or "").strip()
    m = _LOCAL.match(s)
    if m:
        y, mo, d, h, mi = (int(x) for x in m.groups())
        return datetime(y, mo, d, h, mi, tzinfo=ZoneInfo(zone))
    try:
        return parse_ts(s)
    except ValueError:
        raise ValueError(t("point.bad_at", value=repr(raw))) from None


def is_point(goal) -> bool:
    return bool(goal["point_at"])


def _other_zone(zone: str) -> dict | None:
    """The configured zone to write next to the task's own one, if there is another."""
    return next((z for z in settings.zones() if z["name"] != zone), None)


def short_text(dt: datetime, zone: str) -> str:
    return f"{dt.astimezone(ZoneInfo(zone)):%m-%d %H:%M}" + t("paren", x=settings.label_of_zone(zone))


def zone_text(dt: datetime, zone: str) -> str:
    """The task's own wall clock first, then the other configured zone: "11-01 10:00 (Tokyo) = 10-31 18:00 (Los Angeles)".
    With a single configured zone it is just the one."""
    other = _other_zone(zone)
    return short_text(dt, zone) + (t("zones.join") + short_text(dt, other["name"]) if other else "")


def rule_with_start(goal) -> str:
    """For the note written when a rule changes: the rule plus where it starts (changing only the year or the
    first month leaves the rule text the same, so the start is what shows the change)."""
    return t("point.rule_from", rule=rule_text(goal), start=short_text(parse_ts(goal["point_at"]), goal["point_zone"]))


def rule_text(goal) -> str:
    first = parse_ts(goal["point_at"]).astimezone(ZoneInfo(goal["point_zone"]))
    label = t("paren", x=settings.label_of_zone(goal["point_zone"]))
    if goal["point_repeat"] == "monthly":
        return t("point.rule_monthly", day=first.day, time=f"{first:%H:%M}", zone=label)
    return t("point.rule_once", at=f"{first:%m-%d %H:%M}", zone=label)


def occurrences(goal, until: datetime) -> list[datetime]:
    """Every occurrence before `until`, in time order. Monthly ones are computed month by month on the wall
    clock of point_zone: the day of the first occurrence, or the last day of a month that lacks it (the 31st
    in a short month). Nothing is produced after the task was cancelled (abandoned)."""
    first = parse_ts(goal["point_at"])
    stop = until
    if goal["status"] == "abandoned" and goal["done_at"]:
        stop = min(stop, parse_ts(goal["done_at"]))
    if goal["point_repeat"] != "monthly":
        return [first] if first < stop else []
    w = first.astimezone(ZoneInfo(goal["point_zone"]))
    out: list[datetime] = []
    for k in range(1200):   # capped at 100 years so a wrong `until` cannot loop forever
        y, m0 = divmod(w.month - 1 + k, 12)
        y, m = w.year + y, m0 + 1
        moment = datetime(y, m, min(w.day, calendar.monthrange(y, m)[1]), w.hour, w.minute, tzinfo=w.tzinfo)
        if moment >= stop:
            break
        out.append(moment)
    return out


def done_map(entries) -> dict[str, object]:
    """occurrence → the entry that ticked it (the caller has already dropped voided entries)."""
    return {e["occurrence"]: e for e in entries if e["kind"] == "point_done" and e["occurrence"]}


def occurrence_views(goal, entries, now: datetime, until: datetime) -> list[dict]:
    """The state of every occurrence: done / overdue (past its moment, not done) / upcoming / cancelled (not
    done before the task was cancelled; not overdue). A ticked occurrence is listed even if the rule
    changed later and no longer produces it — what was done does not disappear."""
    done = done_map(entries)
    times = {iso(moment): moment for moment in occurrences(goal, until)}
    for key in done:
        times.setdefault(key, parse_ts(key))
    out = []
    for key, moment in sorted(times.items(), key=lambda kv: kv[1]):
        e = done.get(key)
        if e is not None:
            d = parse_ts(e["occurred_at"])
            out.append({"at": key, "state": "done", "done_at": iso(d), "late_s": max(0, int((d - moment).total_seconds())),
                        "entry_id": e["id"]})
        elif goal["status"] == "abandoned":
            out.append({"at": key, "state": "cancelled", "done_at": None, "late_s": 0, "entry_id": None})
        elif moment <= now:
            out.append({"at": key, "state": "overdue", "done_at": None, "late_s": int((now - moment).total_seconds()), "entry_id": None})
        else:
            out.append({"at": key, "state": "upcoming", "done_at": None, "late_s": 0, "entry_id": None})
    zone = goal["point_zone"]
    for o in out:
        moment = parse_ts(o["at"])
        o["text"] = zone_text(moment, zone)
        o["label"] = short_text(moment, zone)
    return out


def visible(o: dict, start: datetime, end: datetime) -> bool:
    """Whether an occurrence belongs in the window [start, end): it occupies [moment, moment + how long it
    was overdue] (just the moment when it was not overdue)."""
    moment = parse_ts(o["at"])
    return moment < end and moment + timedelta(seconds=o["late_s"]) >= start


def late_text(seconds: int) -> str:
    """Character for character the same as lateText in timeline.js: nothing under an hour, hours under a day,
    otherwise days (one decimal under ten days). One float division gives the same float JS has, then it is
    rounded half-up on its exact value (= JS Math.round / toFixed). Exact fractions would not do — the float
    for 1.15 days is really 1.1499…, which JS prints as 1.1 — and Python's own round / format round half to even."""
    ms = seconds * 1000
    if ms < 3600_000:
        return ""
    if ms < 86400_000:
        return t("late.hours", n=_half_up(ms / 3600_000, "1"))
    d = ms / 86400_000
    return t("late.days", n=_half_up(d, "1") if d >= 10 else _half_up(d, "0.1"))


def _half_up(x: float, step: str) -> Decimal:
    return Decimal(x).quantize(Decimal(step), ROUND_HALF_UP)   # Decimal(x) is the float's exact value, not its repr
