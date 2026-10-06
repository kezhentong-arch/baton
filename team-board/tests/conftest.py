"""测试用的配置：一支三个人的虚构团队（一个 owner、两个 member），不碰任何真实配置或数据目录。

直接调规则函数（apply_action、fold……）的测试靠 autouse 的 `_use_cfg` 把这份配置设成进程缺省；
走网页 / 接口的测试用 `client_as()` 起一个应用，以指定的人的身份发请求。
"""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from team_board import auth, config
from team_board.config import Config, parse_config
from team_board.main import create_app

TOKENS = {"linxia": "tok-linxia-0001", "zhouxing": "tok-zhouxing-0002", "suhe": "tok-suhe-0003"}


def raw_cfg(tmp_path: Path, **over) -> dict:
    raw = {
        "title": "团队看板", "lang": "zh", "auth": "local", "host": "127.0.0.1", "port": 22890,
        "data_dir": str(tmp_path / "data"),
        "timezone": {"name": "America/Los_Angeles", "label": "洛杉矶"},
        "second_timezone": {"name": "Asia/Shanghai", "label": "上海"},
        "people": [
            {"id": "linxia", "name": "林夏", "letter": "L", "role": "owner", "token": TOKENS["linxia"]},
            {"id": "zhouxing", "name": "周行", "letter": "Z", "role": "member", "token": TOKENS["zhouxing"]},
            {"id": "suhe", "name": "苏禾", "letter": "S", "role": "member", "token": TOKENS["suhe"]},
        ],
        "lines": ["客户端", "增长", "运营", "管理与协作"],
        "stages": ["业务", "产品", "UI", "开发", "测试"],
        "github": {"enabled": True,
                   "repos": [{"repo": "acme/app", "line": "客户端"}, {"repo": "acme/web", "line": "增长"}],
                   "label_prefix": "stage:",
                   "label_map": [{"pattern": "stage: todo", "state": "To do"}, {"pattern": "stage: dev", "state": "Dev"},
                                 {"pattern": "stage: review", "state": "In review"}, {"pattern": "stage: done", "state": "Done"}],
                   "delivered": ["In review", "Done"]},
    }
    raw.update(over)
    return raw


def make_cfg(tmp_path: Path, **over) -> Config:
    return parse_config(raw_cfg(tmp_path, **over))


@pytest.fixture(autouse=True)
def _use_cfg(tmp_path: Path):
    """每条测试开始时把进程缺省配置设回中文的测试配置（上一条测试可能起过别的语言的应用）。"""
    config.use(make_cfg(tmp_path))
    yield


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "data"


def client_as(tmp_path: Path, person: str = "linxia", via: str = "web", **over):
    """起一个应用，所有请求都算 person 的（绕过登录）。返回 (app, client)。"""
    app = create_app(make_cfg(tmp_path, **over))
    app.dependency_overrides[auth.get_actor] = lambda: auth.Actor(person, via)
    return app, TestClient(app)


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    return client_as(tmp_path)[1]
