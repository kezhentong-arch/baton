"""Shared test setup: every test gets its own data directory and a known config.

The default test config is the Chinese default (so line / stage names are the zh defaults), owner letter C,
main zone Los Angeles plus a second zone (Tokyo, no daylight saving), and a team board that is "connected"
to an address nothing listens on — tests that pull patch `team.fetch_state`.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # make `import app` / `import cli` resolve to this package

from app import settings  # noqa: E402


def make_config(lang: str = "zh", **over) -> dict:
    cfg = settings.default_config(lang, person_id="linxia", name="林夏" if lang == "zh" else "Alex", letter="C",
                                  timezone="America/Los_Angeles", timezone_label="洛杉矶" if lang == "zh" else "LA",
                                  second_timezone="Asia/Tokyo", second_timezone_label="东京" if lang == "zh" else "Tokyo",
                                  team_url="http://127.0.0.1:9")
    cfg.update(over)
    return cfg


@pytest.fixture(autouse=True)
def board_config(tmp_path, monkeypatch):
    monkeypatch.setenv(settings.ENV_DATA, str(tmp_path / "data"))
    monkeypatch.delenv(settings.ENV_TEAM_TOKEN, raising=False)
    monkeypatch.delenv("PERSONAL_BOARD_PRACTICE", raising=False)
    cfg = settings.use(make_config())
    yield cfg
    settings.reload()


@pytest.fixture
def use_config():
    """use_config(lang="en", team_board={...}) → switch the active config inside a test."""
    def _use(lang: str = "zh", **over) -> dict:
        return settings.use(make_config(lang, **over))
    return _use
