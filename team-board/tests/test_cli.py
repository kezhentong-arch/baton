"""命令行：init 生成配置（随机个人令牌、文件只有自己能读）、seed、backup、act、people；仓库里的示例配置只有占位值。"""
import json
import re
import sqlite3
import stat
from pathlib import Path

from team_board import config
from team_board.__main__ import main
from team_board.board.state import fold
from team_board.board.store import board_db_path, connect_board, load_events

REPO = Path(__file__).resolve().parents[1]


def _init(tmp_path, *extra) -> Path:
    path = tmp_path / "cfg" / "config.json"
    assert main(["init", "--config", str(path), "--data-dir", str(tmp_path / "data"), "--port", "22891", *extra]) == 0
    return path


def test_init_writes_a_private_config_with_random_tokens(tmp_path, capsys):
    path = _init(tmp_path, "--lang", "en", "--timezone", "Europe/Berlin", "--timezone-label", "Berlin")
    out = capsys.readouterr().out
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert stat.S_IMODE(path.stat().st_mode) == 0o600                          # 里面有令牌：只有自己能读
    assert raw["lang"] == "en" and raw["auth"] == "local" and raw["host"] == "127.0.0.1" and raw["port"] == 22891
    assert raw["title"] == "Team Board" and raw["timezone"] == {"name": "Europe/Berlin", "label": "Berlin"}
    assert [(p["id"], p["role"], p["letter"]) for p in raw["people"]] == [("alex", "owner", "A"), ("ben", "member", "B"), ("chloe", "member", "C")]
    assert raw["lines"][0]["name"] == "Product" and [s["name"] for s in raw["stages"]] == ["Business", "Product", "Design", "Dev", "Test"]
    assert raw["github"]["enabled"] is False and raw["github"]["label_map"][1] == {"pattern": "stage: dev", "state": "Dev"}
    tokens = [p["token"] for p in raw["people"]]
    assert len(set(tokens)) == 3 and all(re.fullmatch(r"tb_[A-Za-z0-9_-]{32}", t) for t in tokens)
    assert all(t in out for t in tokens) and "Config written" in out
    assert main(["init", "--config", str(path)]) == 2                          # 已有配置不覆盖
    assert json.loads(path.read_text(encoding="utf-8"))["people"][0]["token"] == tokens[0]
    assert main(["init", "--config", str(path), "--data-dir", str(tmp_path / "data"), "--force"]) == 0
    again = json.loads(path.read_text(encoding="utf-8"))
    assert again["lang"] == "zh" and again["people"][0]["name"] == "林夏" and again["people"][0]["token"] not in tokens
    assert [p["letter"] for p in again["people"]] == ["L", "Z", "S"] and again["title"] == "团队看板"
    two = config.parse_config(config.starter_config("zh", second_timezone="Asia/Tokyo", second_timezone_label="东京"))
    assert two.zone2.label == "东京" and two.data_dir == Path("~/.local/share/team-board").expanduser().resolve() and two.port == 10890


def test_init_token_mode_can_listen_on_all_interfaces_but_local_mode_cannot(tmp_path, capsys):
    path = _init(tmp_path, "--auth", "token", "--host", "0.0.0.0")
    assert json.loads(path.read_text(encoding="utf-8"))["host"] == "0.0.0.0"
    capsys.readouterr()
    assert main(["init", "--config", str(tmp_path / "bad.json"), "--host", "0.0.0.0"]) == 2     # 免登录模式不许对外监听
    assert "127.0.0.1" in capsys.readouterr().err and not (tmp_path / "bad.json").exists()


def test_seed_backup_people_and_missing_config(tmp_path, capsys):
    assert main(["seed", "--config", str(tmp_path / "none.json")]) == 2
    assert "team_board init" in capsys.readouterr().err
    path = _init(tmp_path)
    cfg = config.load_config(path)
    assert main(["backup", "--config", str(path)]) == 2                        # 还没有库
    assert main(["seed", "--config", str(path)]) == 0
    assert main(["seed", "--config", str(path), "--lang", "en"]) == 2          # 只往空库里灌
    conn = connect_board(cfg.data_dir)
    goals = fold(load_events(conn)).goals
    conn.close()
    assert len(goals) == 15 and goals[1].title == "会员订阅上线"
    # 练手库可以直接从种子生成（换一种语言也行），不碰正式库
    assert main(["seed", "--config", str(path), "--practice", "--lang", "en"]) == 0
    pconn = connect_board(cfg.data_dir, practice=True)
    assert fold(load_events(pconn)).goals[1].title == "Launch paid membership"
    pconn.close()
    conn = connect_board(cfg.data_dir)
    assert fold(load_events(conn)).goals[1].title == "会员订阅上线"
    conn.close()
    capsys.readouterr()
    out_dir = tmp_path / "bk"
    assert main(["backup", "--config", str(path), "--out", str(out_dir)]) == 0
    backup, = out_dir.glob("board-*.sqlite")
    assert str(backup) in capsys.readouterr().out
    copy = sqlite3.connect(backup)
    assert copy.execute("SELECT COUNT(*) FROM goals").fetchone()[0] == 15      # 备份是一份完整可用的库
    copy.close()
    assert board_db_path(cfg.data_dir).exists()
    assert main(["people", "--config", str(path)]) == 0
    listed = capsys.readouterr().out
    assert "linxia" in listed and "owner" in listed and cfg.persons[0].token in listed


def test_act_is_dry_run_without_execute_and_identity_is_the_persons_token(tmp_path, capsys, monkeypatch):
    path = _init(tmp_path)
    cfg = config.load_config(path)
    from team_board import mcp
    sent = []

    def fake_request(self, method, url_path, body=None, query=None):
        sent.append((method, url_path, body, self.token, self.base))
        return {"ok": True}

    monkeypatch.setattr(mcp.Board, "request", fake_request)
    monkeypatch.delenv("TEAM_BOARD_URL", raising=False)
    monkeypatch.delenv("TEAM_BOARD_TOKEN", raising=False)
    monkeypatch.setenv("TEAM_BOARD_CONFIG", str(path))
    args = ["act", "create", "--param", "title=新目标", "--param", "owner=suhe", "--param", "line=增长", "--as", "linxia"]
    assert main(args) == 0 and sent == []                                      # 不带 --execute：只打印
    assert "新目标" in capsys.readouterr().out
    assert main([*args, "--execute", "--practice"]) == 0
    assert sent == [("POST", "/api/board/practice/act", {"action": "create", "params": {"title": "新目标", "owner": "suhe", "line": "增长"}},
                     cfg.persons[0].token, "http://127.0.0.1:22891")]          # 地址取本机配置，令牌是 --as 那个人的
    assert main(["act", "state", "--as", "zhouxing"]) == 0 and sent[-1][:2] == ("GET", "/api/board/state") and sent[-1][3] == cfg.persons[1].token
    assert main(["act", "create", "--param", "oops"]) == 2 and main(["act", "state", "--param", "a=b"]) == 2
    assert main(["act", "state", "--as", "nobody"]) == 1
    monkeypatch.setenv("TEAM_BOARD_TOKEN", "tok-from-env")
    assert main(["act", "actions", "--url", "https://board.example.com"]) == 0
    assert sent[-1] == ("GET", "/api/board/actions", None, "tok-from-env", "https://board.example.com")


def test_example_config_in_the_repo_is_valid_and_holds_only_placeholders():
    raw = json.loads((REPO / "config.example.json").read_text(encoding="utf-8"))
    cfg = config.parse_config(raw)
    assert cfg.auth == "token" and cfg.github.enabled is False
    assert all(p["token"].startswith("CHANGE-ME") for p in raw["people"])       # 占位，不是能用的令牌
    assert not re.search(r"tb_[A-Za-z0-9_-]{20,}", json.dumps(raw))
    ignore = (REPO / ".gitignore").read_text(encoding="utf-8")
    assert "config.json" in ignore and "*.sqlite" in ignore
