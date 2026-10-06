import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from team_board.board.store import append_event, board_db_path, connect_board, load_events

NOW = datetime(2026, 10, 1, 18, 0, tzinfo=timezone.utc)


def test_events_are_append_only(tmp_path):
    conn = connect_board(tmp_path)
    eid = append_event(conn, subject="goal:1", kind="goal.proposed", payload={"title": "看板"},
                       actor="linxia", via="web", now=NOW)
    conn.commit()
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute("UPDATE events SET kind='x' WHERE id=?", (eid,))
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute("DELETE FROM events WHERE id=?", (eid,))
    assert board_db_path(tmp_path).name == "board.sqlite"


def test_backfill_flag_and_timezone_roundtrip(tmp_path):
    conn = connect_board(tmp_path)
    past = datetime(2026, 9, 28, 10, 0, tzinfo=timezone(timedelta(hours=-7)))
    append_event(conn, subject="goal:1", kind="goal.proposed", payload={"title": "看板"},
                 actor="linxia", via="ai", now=NOW, occurred_at=past)
    conn.commit()
    (e,) = load_events(conn)
    assert e.backfill is True
    assert e.occurred_at == past            # 同一时刻，换算成 UTC 存也不丢
    with pytest.raises(ValueError):
        append_event(conn, subject="goal:1", kind="x", payload={}, actor="linxia", via="web",
                     now=NOW, occurred_at=NOW + timedelta(hours=1))
