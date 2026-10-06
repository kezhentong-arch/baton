"""Online SQLite backup (includes what is committed in the WAL): a unique file name per run, checked for
integrity, keeping the latest 30."""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.i18n import t  # noqa: E402
from app.settings import data_dir  # noqa: E402
from app.store import db_path  # noqa: E402


def backup() -> Path:
    root = data_dir() / "backups"
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    target = root / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ") + ".sqlite")
    src = sqlite3.connect(f"file:{db_path(False)}?mode=ro", uri=True)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)
        if dst.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError(t("cli.backup_bad"))
    finally:
        src.close()
        dst.close()
    target.chmod(0o600)
    for old in sorted(root.glob("2*Z.sqlite"), reverse=True)[30:]:   # only this command's own files; `reset` backups are kept
        old.unlink()
    return target
