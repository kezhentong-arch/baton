"""Constants and time helpers.

Time rule: store UTC with an offset, display in the configured main time zone; when asking a human to
confirm a moment, write it in both configured zones (or just the one, if no second zone is set).
Nothing here depends on the host's time zone.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone

from app import settings
from app.i18n import every, t

VERSION = "1.0.0"   # shown top-right on the page; also the HTTP Server header and the User-Agent of team-board pulls

# Birth numbers: the moment a goal is created here it gets "<your letter><sequence>" (e.g. A19). The number
# never changes and is never reused, even after a reset. Once the goal is pushed to the team board its
# display number becomes the team's G number, the team board records the birth number as its source, and
# either number still finds the goal. Commit messages can cite it.
BIRTH_RE = re.compile(r"^([A-Z])([1-9]\d*)$")

# Entry kinds. start / result / wrap are the three everyday notes (starting, a visible result, wrapping up);
# digest = a lesson or rule written into a handbook (done the moment it is logged, drawn as a gold dot —
# green is reserved for "goal completed"); the rest are stage and goal events.
ENTRY_KINDS: tuple[str, ...] = (
    "start", "result", "wrap", "note", "digest", "stage_start", "stage_end", "goal_create", "due", "complete", "abandon",
    "point_done",   # a point task done once (app/points.py); voiding it makes the dot hollow again
    "release",      # a long-running row closes a version: new version badge + what this version did
    "summary",      # a goal already on the team board changed its "what" / "done" text; pushed as an edit
)
LOG_KINDS: tuple[str, ...] = ("start", "result", "wrap", "note", "digest")
# On a team line these kinds are pushed to the team board (each entry carries unpushed / pushed / not pushed).
SYNC_KINDS: frozenset[str] = frozenset({"goal_create", "stage_start", "stage_end", "due", "complete", "abandon", "summary"})
SYNC_STATES: tuple[str, ...] = ("pending", "pushed", "skip")

TOOLS: tuple[str, ...] = ("claude", "codex", "web", "seed")

FUTURE_TOLERANCE = timedelta(minutes=5)  # an event may be at most 5 minutes in the future (clock skew); later is a typo


def kind_label(kind: str) -> str:
    return t(f"kind.{kind}") if kind in ENTRY_KINDS else kind


def sync_label(state: str | None) -> str:
    return t(f"sync.{state}") if state in SYNC_STATES else ""


def is_default_abandon(text: str) -> bool:
    """The placeholder written when a goal is abandoned without a reason; it does not count as a reason."""
    return text in every("abandon.default")


def version_key(version: str | None) -> tuple[int, ...] | None:
    """The first run of digits in a version string, for comparing versions ("v1.4.2", "handbook 1.5.16");
    None when there is no number. Version badges and changelogs of long-running rows sort by it."""
    m = re.search(r"\d+(?:\.\d+)*", version or "")
    return tuple(int(x) for x in m.group(0).split(".")) if m else None


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_ts(s: str) -> datetime:
    """ISO string with an offset → aware datetime. A string without a zone is rejected, never guessed."""
    dt = datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError(t("time.no_offset", value=repr(s)))
    return dt


def iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        raise ValueError(t("time.naive"))
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def local_text(dt: datetime | None, fmt: str = "%m-%d %H:%M") -> str:
    return "—" if dt is None else dt.astimezone(settings.tz()).strftime(fmt)


def zoned(dt: datetime, zone: dict, fmt: str = "%m-%d %H:%M") -> str:
    """"10-02 09:30 (Los Angeles)" — one moment in one configured zone, with its label."""
    from zoneinfo import ZoneInfo
    return dt.astimezone(ZoneInfo(zone["name"])).strftime(fmt) + t("paren", x=zone["label"])


def both_zones(dt: datetime, fmt: str = "%m-%d %H:%M") -> str:
    """The line to show a human when confirming a moment: every configured zone, main first, joined by "="."""
    return t("zones.join").join(zoned(dt, z, fmt) for z in settings.zones())


def local_day(dt: datetime) -> date:
    return dt.astimezone(settings.tz()).date()


def day_bounds(d: date) -> tuple[datetime, datetime]:
    """[00:00, next 00:00) of a date in the main time zone."""
    start = datetime(d.year, d.month, d.day, tzinfo=settings.tz())
    return start, start + timedelta(days=1)


def gnum_key(gnum: str) -> tuple:
    """G2.10 sorts after G2.9: compare the numeric levels. Example E numbers and birth numbers not yet
    pushed sort after G numbers."""
    head, _, rest = gnum.partition(".") if gnum else ("", "", "")
    prefix = head[:1]
    nums = []
    for part in (head[1:], *rest.split(".")) if gnum else ():
        nums.append(int(part) if part.isdigit() else 0)
    return ({"G": 0, "E": 1}.get(prefix, 2), tuple(nums))
