"""看板的数据库（sqlite：正式 board.sqlite；练手 practice.sqlite 是另一份文件）。

events 只追加：改期、补录、纠错都追加新事件，触发器拒绝 UPDATE / DELETE——
「延期被改没」在数据库层面就做不到。
"""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from fastapi import Request

from team_board.board.model import BACKFILL_GRACE, FUTURE_TOLERANCE, iso, parse_ts, utc_now
from team_board.i18n import t

# gh_incomplete：事件没取全的单。每轮同步都重试，补齐才删；页面一直提示，不随游标前移而消失
_SCHEMA = """
CREATE TABLE IF NOT EXISTS goals(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  subject TEXT NOT NULL,
  kind TEXT NOT NULL,
  payload TEXT NOT NULL,
  actor TEXT NOT NULL,
  via TEXT NOT NULL CHECK(via IN ('web','ai','seed')),
  occurred_at TEXT NOT NULL,
  recorded_at TEXT NOT NULL,
  backfill INTEGER NOT NULL CHECK(backfill IN (0,1))
);
CREATE INDEX IF NOT EXISTS idx_events_subject ON events(subject, occurred_at);
CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events
BEGIN SELECT RAISE(ABORT, 'events are append-only: no UPDATE'); END;
CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events
BEGIN SELECT RAISE(ABORT, 'events are append-only: no DELETE'); END;
CREATE TABLE IF NOT EXISTS gh_issues(
  repo TEXT NOT NULL, number INTEGER NOT NULL,
  title TEXT NOT NULL, url TEXT NOT NULL, state TEXT NOT NULL,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, closed_at TEXT,
  milestone_number INTEGER, parent_number INTEGER,
  labels TEXT NOT NULL, assignees TEXT NOT NULL,
  timeline_total INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY(repo, number)
);
CREATE TABLE IF NOT EXISTS gh_incomplete(
  repo TEXT NOT NULL, number INTEGER NOT NULL, reason TEXT NOT NULL,
  first_seen TEXT NOT NULL, last_tried TEXT NOT NULL,
  PRIMARY KEY(repo, number)
);
CREATE TABLE IF NOT EXISTS gh_events(
  repo TEXT NOT NULL, number INTEGER NOT NULL,
  type TEXT NOT NULL, at TEXT NOT NULL, ref TEXT NOT NULL DEFAULT '',
  UNIQUE(repo, number, type, at, ref)
);
CREATE TABLE IF NOT EXISTS gh_milestones(
  repo TEXT NOT NULL, number INTEGER NOT NULL,
  title TEXT NOT NULL, state TEXT NOT NULL, due_on TEXT,
  created_at TEXT NOT NULL, closed_at TEXT,
  PRIMARY KEY(repo, number)
);
CREATE TABLE IF NOT EXISTS gh_cursor(repo TEXT PRIMARY KEY, since TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS gh_sync_runs(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at TEXT NOT NULL, finished_at TEXT,
  ok INTEGER, issues_seen INTEGER NOT NULL DEFAULT 0,
  error TEXT NOT NULL DEFAULT '', warnings TEXT NOT NULL DEFAULT '[]'
);
"""


@dataclass(frozen=True)
class Event:
    id: int
    subject: str        # goal:12 | version:owner/repo#9 | board | inbox
    kind: str
    payload: dict
    actor: str          # 配置里的人的 id
    via: str            # web | ai | seed
    occurred_at: datetime
    recorded_at: datetime
    backfill: bool


def board_db_path(data_dir: Path, practice: bool = False) -> Path:
    """正式库 board.sqlite；练手库 practice.sqlite 是另一份文件（让人真实操作一遍、不碰正式数据）。"""
    return data_dir / "board" / ("practice.sqlite" if practice else "board.sqlite")


# 练手库独有的一张表：这份副本是什么时候复制的。练手页页头据此写「练手数据 x 点重置」，
# 而不是拿正式看板的「GitHub 数据超过 30 分钟没更新」吓人（练手库从不同步，那条提醒会一直亮）
_PRACTICE_META = "CREATE TABLE IF NOT EXISTS practice_meta(reset_at TEXT NOT NULL);"


def build_practice(data_dir: Path, from_seed: bool = False, seed_lang: str | None = None) -> Path:
    """练手库 = 此刻正式库的整份副本（含示例目标和同步来的 GitHub 数据），重置就是重做一遍。
    先删旧文件和它的 -wal / -shm，再用 SQLite 在线备份复制（正式库正在被写也能拿到一致的一份），最后记下复制的时刻。
    from_seed=True（命令行 `seed --practice`）时不复制正式库，改成往空的练手库里灌虚构的示例数据。"""
    dst = board_db_path(data_dir, practice=True)
    dst.parent.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        Path(f"{dst}{suffix}").unlink(missing_ok=True)
    src = board_db_path(data_dir)
    d = sqlite3.connect(dst, timeout=30)
    d.row_factory = sqlite3.Row
    try:
        if src.exists() and not from_seed:
            s = sqlite3.connect(src)
            try:
                s.backup(d)
            finally:
                s.close()
        d.executescript(_SCHEMA + _PRACTICE_META)
        if from_seed:
            from team_board import config, seed      # 延迟导入：seed 要用 actions，actions 又要用本模块
            seed.seed_demo(d, seed_lang or config.current().lang)
        d.execute("INSERT INTO practice_meta(reset_at) VALUES(?)", (iso(utc_now()),))
        d.commit()
    finally:
        d.close()
    return dst


def practice_reset_at(conn: sqlite3.Connection) -> datetime | None:
    """练手库是什么时候复制的。没有这张表（很早以前建的练手库）返回 None，页头改说「上次重置」——
    这是旧副本的正常情况，不是出错；下次重置就有了。"""
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='practice_meta'").fetchone() is None:
        return None
    row = conn.execute("SELECT reset_at FROM practice_meta ORDER BY rowid DESC LIMIT 1").fetchone()
    return parse_ts(row[0]) if row else None


def is_practice(request: Request) -> bool:
    """练手看板的页面和接口都带 /practice 前缀，连的就是练手库。"""
    path = request.url.path
    return path.startswith(("/board/practice", "/api/board/practice"))


def connect_board(data_dir: Path, practice: bool = False) -> sqlite3.Connection:
    path = board_db_path(data_dir, practice)
    if practice and not path.exists():
        build_practice(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False：每个请求一条连接、串行使用，但请求可能换线程。
    # timeout=30：后台同步写库时，网页写入排队等锁，而不是 5 秒后报 database is locked
    conn = sqlite3.connect(path, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_SCHEMA)
    return conn


def get_board_db(request: Request) -> Iterator[sqlite3.Connection]:
    conn = connect_board(request.app.state.cfg.data_dir, practice=is_practice(request))
    try:
        yield conn
    finally:
        conn.close()


def new_goal_id(conn: sqlite3.Connection, now: datetime) -> int:
    cur = conn.execute("INSERT INTO goals(created_at) VALUES(?)", (iso(now),))
    return int(cur.lastrowid)


def append_event(conn: sqlite3.Connection, *, subject: str, kind: str, payload: dict,
                 actor: str, via: str, now: datetime,
                 occurred_at: datetime | None = None) -> int:
    occ = occurred_at or now
    if occ > now + FUTURE_TOLERANCE:
        raise ValueError(t("err.future"))
    backfill = 1 if now - occ > BACKFILL_GRACE else 0
    cur = conn.execute(
        "INSERT INTO events(subject,kind,payload,actor,via,occurred_at,recorded_at,backfill)"
        " VALUES(?,?,?,?,?,?,?,?)",
        (subject, kind, json.dumps(payload, ensure_ascii=False), actor, via,
         iso(occ), iso(now), backfill))
    return int(cur.lastrowid)


def load_events(conn: sqlite3.Connection) -> list[Event]:
    return [
        Event(id=r["id"], subject=r["subject"], kind=r["kind"], payload=json.loads(r["payload"]),
              actor=r["actor"], via=r["via"], occurred_at=parse_ts(r["occurred_at"]),
              recorded_at=parse_ts(r["recorded_at"]), backfill=bool(r["backfill"]))
        for r in conn.execute("SELECT * FROM events ORDER BY occurred_at, id")
    ]
