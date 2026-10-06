"""Example / practice data = a mirror of the main data + two hypothetical cases.

The example board never keeps a frozen copy: every time the example page is opened the main database is
copied into memory and the hypothetical cases are laid on top, so the "real" part of the example can never
drift from the main board.

The hypothetical cases show how a bigger piece of work looks when one owner runs it end to end (dates are
relative to today, in the main time zone; lines and stages are taken from the config by position):
1. a goal split into blocks A and B, where B waits on someone else's block before it can be built;
2. a parent goal whose blocks are handed to others — only the parent is on this board.
Example numbers start with E (E1, E1.1) so they can never be mistaken for real G numbers.

The practice database is the same thing written to a file (reset = rebuild from the main data as it is
now); nothing done there touches the main or the example board.
"""
from __future__ import annotations

import sqlite3
import threading
from datetime import date, datetime, time, timedelta
from pathlib import Path

from app import settings
from app.actions import ActionError, apply_action
from app.i18n import t
from app.model import iso, local_day, utc_now
from app.store import db_path, open_db, set_meta


def _at(base: date, day: float) -> str:
    return iso(datetime.combine(base, time(10), tzinfo=settings.tz()) + timedelta(days=day))


def seed_hypothetical(conn: sqlite3.Connection, now: datetime) -> int:
    """Lay the two hypothetical cases over `conn` (which already holds the main data). Returns the number of actions."""
    n = 0
    team = settings.team_line_names() or settings.line_names()
    line_a, line_b = team[min(1, len(team) - 1)], team[0]
    names = settings.stage_names()
    stage = lambda i: names[min(i, len(names) - 1)]  # noqa: E731 — 0 business, 1 product, 2 design, 3 dev, 4 test
    task = t("sample.task")

    def act(action: str, **params):
        nonlocal n
        try:
            r = apply_action(conn, action, params, now, internal=True)
        except ActionError:   # a config with fewer stages or lines than the story needs: skip the step, keep the page
            return None
        n += 1
        return r

    # 1. Hypothetical: one goal, two blocks; block B's build waits on someone else's block C
    base = local_day(now) - timedelta(days=40)
    at = lambda d: _at(base, d)  # noqa: E731
    due = lambda d: str(base + timedelta(days=d))  # noqa: E731
    act("goal_create", title=t("sample.e1.title"), line=line_a, gnum="E1", due=due(24), occurred_at=at(0),
        next_step=t("sample.e1.next"), _sync="pushed")
    act("stage_start", goal="E1", stage=stage(0), occurred_at=at(0), task=task, tool="seed", _sync="pushed")
    act("stage_end", goal="E1", stage=stage(0), occurred_at=at(3), task=task, tool="seed", _sync="pushed")
    act("goal_create", title=t("sample.e11.title"), line=line_a, gnum="E1.1", parent_gnum="E1", due=due(20), occurred_at=at(3),
        next_step=t("sample.e11.next"), _sync="pushed")
    act("goal_create", title=t("sample.e12.title"), line=line_a, gnum="E1.2", parent_gnum="E1", due=due(25), occurred_at=at(3),
        next_step=t("sample.e12.next"), _sync="pushed")
    plan = [("E1.1", 1, 3, 7), ("E1.1", 2, 5, 9), ("E1.1", 3, 8, 16), ("E1.1", 4, 14, 19), ("E1.1", 1, 15, 16),
            ("E1.2", 1, 3, 6), ("E1.2", 3, 18, 28), ("E1.2", 4, 24, None), ("E1.2", 3, 30, None)]
    steps = []
    for g, st, a, b in plan:
        steps.append((a, "stage_start", g, stage(st)))
        if b is not None:
            steps.append((b, "stage_end", g, stage(st)))
    steps += [(19, "complete", "E1.1", None),
              (6, "log", "E1.2", t("sample.e12.log_wait")),
              (18, "log", "E1.2", t("sample.e12.log_go")),
              (16, "log", "E1.1", t("sample.e11.log_back"))]
    for day, op, g, x in sorted(steps, key=lambda s: s[0]):
        if op == "log":
            act("log", goal=g, text=x, kind="result", occurred_at=at(day), task=task, tool="seed")
        elif op == "complete":
            act("complete", goal=g, occurred_at=at(day), task=task, tool="seed", _sync="pushed")
        else:
            act(op, goal=g, stage=x, occurred_at=at(day), task=task, tool="seed", _sync="pushed")

    # 2. Hypothetical: a parent goal whose three blocks belong to others (they are on the team board, not here)
    base = local_day(now) - timedelta(days=6)
    act("goal_create", title=t("sample.e2.title"), line=line_b, gnum="E2", due=due(10), occurred_at=at(0),
        next_step=t("sample.e2.next"), _sync="pushed")
    act("stage_start", goal="E2", stage=stage(0), occurred_at=at(0), task=task, tool="seed", _sync="pushed")
    act("stage_end", goal="E2", stage=stage(0), occurred_at=at(0.3), task=task, tool="seed", _sync="pushed")
    act("log", goal="E2", kind="result", text=t("sample.e2.log"), occurred_at=at(0.3), task=task, tool="seed")
    act("todo_add", text=t("sample.e2.todo"), goal="E2")
    return n


def _copy_into(src: sqlite3.Connection, dst: sqlite3.Connection, dataset: str, now: datetime) -> None:
    """Copy all of src (the main database) into dst, tag the data set, then lay the hypothetical cases on top."""
    src.backup(dst)
    dst.execute("PRAGMA foreign_keys=ON")
    with dst:
        set_meta(dst, "dataset", dataset)
    seed_hypothetical(dst, now)


def snapshot(real_path: Path, now: datetime | None = None) -> sqlite3.Connection:
    """For the example board: an in-memory mirror of the main database as it is now + the hypothetical cases.
    Read-only (the page layer blocks writes); shared by all threads of the process."""
    now = now or utc_now()
    src = open_db(real_path)
    try:
        dst = sqlite3.connect(":memory:", check_same_thread=False)
        dst.row_factory = sqlite3.Row
        _copy_into(src, dst, "sample", now)
        return dst
    finally:
        src.close()


class SampleMirror:
    """Cache of the example board's mirror: reused while the main database is unchanged, rebuilt once any
    connection has committed to it.

    Change is detected with PRAGMA data_version on a long-lived read-only connection — the number changes only
    after another connection commits. File mtime would not do: in WAL mode the main file need not change.
    """

    def __init__(self, real_path: Path):
        self.real_path = real_path
        self._watch = open_db(real_path)
        self._conn: sqlite3.Connection | None = None
        self._ver: int | None = None
        self._lock = threading.Lock()

    def conn(self) -> sqlite3.Connection:
        with self._lock:
            ver = self._watch.execute("PRAGMA data_version").fetchone()[0]
            if self._conn is None or ver != self._ver:
                if self._conn is not None:
                    self._conn.close()
                self._conn = snapshot(self.real_path)
                self._ver = ver
            return self._conn


def build_practice(now: datetime | None = None) -> Path:
    """Rebuild the practice database from scratch: the main data as it is now + the hypothetical cases."""
    now = now or utc_now()
    path = db_path(True)
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(path) + suffix)
        if p.exists():
            p.unlink()
    src = open_db(db_path(False))
    dst = open_db(path)
    try:
        _copy_into(src, dst, "practice", now)
    finally:
        dst.close()
        src.close()
    return path
