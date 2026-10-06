"""sqlite storage. Data lives in the user's data directory; practice mode is a second file.

Append-only: nothing is deleted. A wrong entry is voided (voided_at + reason) so the trail stays.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from app.model import BIRTH_RE
from app.settings import data_dir

MAIN_DB = "board.sqlite"
PRACTICE_DB = "practice.sqlite"
# Three data sets behind URL prefixes: main, example (read-only demo) and practice (play freely, resettable).
# The example is never written to a file: it is a live mirror of the main database (app/sample.py).
MODES: dict[str, str | None] = {"": MAIN_DB, "sample": None, "practice": PRACTICE_DB}

SCHEMA = """
CREATE TABLE IF NOT EXISTS goals (
  id INTEGER PRIMARY KEY,
  gnum TEXT UNIQUE,
  birth TEXT,
  line TEXT NOT NULL,
  title TEXT NOT NULL,
  owner TEXT NOT NULL,
  parent_gnum TEXT,
  status TEXT NOT NULL DEFAULT 'active',
  next_step TEXT NOT NULL DEFAULT '',
  blocker TEXT NOT NULL DEFAULT '',
  version_name TEXT NOT NULL DEFAULT '',
  source TEXT NOT NULL DEFAULT 'local',
  team_id INTEGER,
  long_term INTEGER NOT NULL DEFAULT 0,
  due TEXT,
  baseline_due TEXT,
  point_at TEXT,
  point_zone TEXT,
  point_repeat TEXT,
  what TEXT,
  done_what TEXT,
  created_at TEXT NOT NULL,
  done_at TEXT,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS entries (
  id INTEGER PRIMARY KEY,
  goal_id INTEGER NOT NULL REFERENCES goals(id),
  stage TEXT,
  kind TEXT NOT NULL,
  text TEXT NOT NULL DEFAULT '',
  task TEXT NOT NULL DEFAULT '',
  tool TEXT NOT NULL DEFAULT '',
  occurred_at TEXT NOT NULL,
  recorded_at TEXT NOT NULL,
  sync TEXT,
  synced_at TEXT,
  team_ref TEXT NOT NULL DEFAULT '',
  voided_at TEXT,
  void_reason TEXT NOT NULL DEFAULT '',
  occurrence TEXT,
  version TEXT
);
CREATE INDEX IF NOT EXISTS entries_goal ON entries(goal_id, occurred_at);
CREATE INDEX IF NOT EXISTS entries_time ON entries(occurred_at);
-- One occurrence of a point task can be ticked only once, even when two conversations tick at the same moment.
CREATE UNIQUE INDEX IF NOT EXISTS entries_point_once ON entries(goal_id, occurrence)
  WHERE kind='point_done' AND voided_at IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS goals_birth ON goals(birth) WHERE birth IS NOT NULL;
CREATE TABLE IF NOT EXISTS todos (
  id INTEGER PRIMARY KEY,
  goal_id INTEGER REFERENCES goals(id),
  text TEXT NOT NULL,
  created_at TEXT NOT NULL,
  done_at TEXT
);
CREATE TABLE IF NOT EXISTS notes (
  id INTEGER PRIMARY KEY,
  text TEXT NOT NULL,
  goal_id INTEGER REFERENCES goals(id),
  created_at TEXT NOT NULL,
  resolved_at TEXT,
  summary TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS action_receipts (
  request_id TEXT PRIMARY KEY,
  digest TEXT NOT NULL,
  result TEXT NOT NULL
);
"""


def db_path(practice: bool) -> Path:
    return data_dir() / (PRACTICE_DB if practice else MAIN_DB)


def mode_db_path(mode: str) -> Path:
    name = MODES[mode]
    if name is None:
        raise ValueError(f"the {mode} board has no file; use app.sample.SampleMirror")
    return data_dir() / name


def open_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    return conn


def birth_floor(conn: sqlite3.Connection) -> dict[str, int]:
    """How far each letter has been issued: the larger of the highest birth number in the table and the
    watermark kept in meta (the watermark is what survives a reset, so numbers are never reissued)."""
    floor: dict[str, int] = {}
    for r in conn.execute("SELECT key, value FROM meta WHERE key LIKE 'birth_seq_%'"):
        floor[r["key"][len("birth_seq_"):]] = int(r["value"] or 0)
    for r in conn.execute("SELECT birth FROM goals WHERE birth IS NOT NULL"):
        if m := BIRTH_RE.match(r["birth"]):
            floor[m.group(1)] = max(floor.get(m.group(1), 0), int(m.group(2)))
    return floor


def next_birth(conn: sqlite3.Connection, letter: str) -> str:
    """Issue the next birth number and record the watermark. The sequence continues after the highest
    number this letter ever had; numbers are never reused."""
    seq = birth_floor(conn).get(letter, 0) + 1
    while conn.execute("SELECT 1 FROM goals WHERE gnum=? OR birth=?", (f"{letter}{seq}",) * 2).fetchone():
        seq += 1   # someone set this number by hand: skip it
    set_meta(conn, f"birth_seq_{letter}", str(seq))
    return f"{letter}{seq}"


def find_goal(conn: sqlite3.Connection, key) -> sqlite3.Row | None:
    """Display number (G2.2, or a birth number not yet pushed) → birth number (still found after the goal
    got a G number) → internal id."""
    key = str(key).strip()
    row = conn.execute("SELECT * FROM goals WHERE gnum=?", (key,)).fetchone()
    if row is None:   # a16 / g2.2 work too: lookup is case-insensitive
        row = conn.execute("SELECT * FROM goals WHERE gnum=? OR birth=? ORDER BY gnum=? DESC", (key.upper(),) * 3).fetchone()
    if row is None and key.isdigit():
        row = conn.execute("SELECT * FROM goals WHERE id=?", (int(key),)).fetchone()
    return row


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return None if row is None else row["value"]


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute("INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                 (key, value))
