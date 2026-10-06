"""登录与身份：本地试用模式（免登录、页面上选「我是谁」）、令牌模式（个人令牌登录 / Bearer）、
owner 与 member 能做什么。这里不绕过登录：请求走真实的 get_actor。"""
import pytest
from fastapi.testclient import TestClient

from team_board import config
from team_board.auth import COOKIE_PERSON, COOKIE_SESSION
from team_board.main import create_app
from tests.conftest import TOKENS, make_cfg, raw_cfg


def _app(tmp_path, **over) -> TestClient:
    return TestClient(create_app(make_cfg(tmp_path, **over)))


def _bearer(person: str) -> dict:
    return {"Authorization": f"Bearer {TOKENS[person]}"}


def _create(c, headers=None, **params):
    return c.post("/api/board/act", json={"action": "create", "params": params}, headers=headers or {})


# ---------------------------------------------------------------- 本地试用模式

def test_local_mode_needs_no_login_and_defaults_to_the_first_owner(tmp_path):
    c = _app(tmp_path)
    page = c.get("/board")
    assert page.status_code == 200 and "我是：林夏" in page.text and "本地试用模式" in page.text
    assert "退出登录" not in page.text                       # 没有登录态，不给「退出登录」
    assert c.get("/api/board/state").json()["me"] == {"id": "linxia", "name": "林夏", "role": "owner", "letter": "L"}
    assert c.get("/login", follow_redirects=False).headers["location"] == "/board"


def test_local_mode_pick_who_i_am_on_the_page(tmp_path):
    c = _app(tmp_path)
    page = c.get("/board").text
    assert 'action="/whoami"' in page and 'value="zhouxing"' in page and 'value="suhe"' in page
    r = c.post("/whoami", data={"person": "zhouxing", "next": "/board"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/board"
    cookie = r.headers["set-cookie"]
    assert f"{COOKIE_PERSON}=zhouxing" in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie
    assert "我是：周行" in c.get("/board").text
    assert c.get("/api/board/state").json()["me"]["id"] == "zhouxing"
    denied = _create(c, title="成员想另开一棵", line="增长", owner="zhouxing")       # 选成了成员，权限也跟着是成员的
    assert denied.status_code == 403 and "团队负责人" in denied.json()["error"]
    c.post("/whoami", data={"person": "nobody", "next": "/board"})                  # 不认识的人：不换
    assert c.get("/api/board/state").json()["me"]["id"] == "zhouxing"
    assert c.post("/whoami", data={"person": "linxia", "next": "https://evil.example/x"},
                  follow_redirects=False).headers["location"] == "/board"          # 不往站外跳


def test_local_mode_also_accepts_a_personal_token_and_marks_it_as_via_ai(tmp_path):
    c = _app(tmp_path)
    ok = _create(c, _bearer("linxia"), title="AI 立的项", line="增长", owner="suhe")
    assert ok.status_code == 200
    assert "林夏（经 AI）" in c.get(f"/board/goal/{ok.json()['goal_id']}").text
    assert c.get("/api/board/state", headers=_bearer("suhe")).json()["me"]["id"] == "suhe"
    bad = c.get("/api/board/state", headers={"Authorization": "Bearer nope"})
    assert bad.status_code == 401


def test_local_mode_refuses_to_listen_beyond_loopback(tmp_path):
    """免登录的模式谁连上都能以任何人的身份写：监听非回环地址时拒绝启动，并说清怎么办。"""
    for host in ("0.0.0.0", "192.0.2.10", "::", "board.example.com"):
        with pytest.raises(config.ConfigError) as e:
            make_cfg(tmp_path, host=host)
        assert "token" in str(e.value) and host in str(e.value)
    for host in ("127.0.0.1", "localhost", "::1"):
        assert make_cfg(tmp_path, host=host).host == host
    assert make_cfg(tmp_path, host="0.0.0.0", auth="token").host == "0.0.0.0"       # 令牌模式可以对外监听
    # 命令行临时改 --host 也拦
    import json
    from team_board.__main__ import main
    path = tmp_path / "c.json"
    path.write_text(json.dumps(raw_cfg(tmp_path)), encoding="utf-8")
    assert main(["start", "--config", str(path), "--host", "0.0.0.0"]) == 2


# ---------------------------------------------------------------- 令牌模式

def test_token_mode_pages_redirect_to_login_and_api_says_401(tmp_path):
    c = _app(tmp_path, auth="token")
    r = c.get("/board/goal/3?ok=1", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login?next=/board/goal/3?ok=1"
    for path in ("/board", "/board/practice", "/board/sample"):
        assert c.get(path, follow_redirects=False).status_code == 303
    api = c.get("/api/board/state")
    assert api.status_code == 401 and "Bearer" in api.json()["error"]
    assert c.post("/api/board/act", json={"action": "create", "params": {}}).status_code == 401
    assert c.post("/api/board/practice/act", json={"action": "create", "params": {}}).status_code == 401
    assert c.post("/whoami", data={"person": "linxia"}).status_code == 404           # 令牌模式没有「选我是谁」
    assert c.get("/healthz").json() == {"ok": True}
    login = c.get("/login").text
    assert 'type="password"' in login and "个人令牌" in login and '<html lang="zh-CN">' in login


def test_token_mode_browser_login_sets_a_safe_cookie_and_logout_clears_it(tmp_path):
    c = _app(tmp_path, auth="token")
    bad = c.post("/login", data={"token": "wrong", "next": "/board"})
    assert bad.status_code == 401 and "令牌不对" in bad.text
    r = c.post("/login", data={"token": TOKENS["suhe"], "next": "/board/practice"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/board/practice"
    cookie = r.headers["set-cookie"]
    assert COOKIE_SESSION in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie and "Secure" not in cookie
    page = c.get("/board").text
    assert "我是：苏禾" in page and "退出登录" in page and 'action="/whoami"' not in page
    assert c.get("/api/board/state").json()["me"]["id"] == "suhe"
    out = c.post("/logout", follow_redirects=False)
    assert out.status_code == 303 and out.headers["location"] == "/login"
    c.cookies.clear()
    assert c.get("/board", follow_redirects=False).status_code == 303
    # 反向代理说外面是 HTTPS：cookie 带 Secure
    https = _app(tmp_path, auth="token").post("/login", data={"token": TOKENS["suhe"]}, follow_redirects=False,
                                              headers={"X-Forwarded-Proto": "https"})
    assert "Secure" in https.headers["set-cookie"]


def test_token_mode_identity_comes_from_the_token_never_from_a_claim(tmp_path):
    """AI / 命令行用 Authorization: Bearer <个人令牌>；身份只由令牌决定，自报的头、参数一概不认。"""
    c = _app(tmp_path, auth="token")
    spoof = {**_bearer("zhouxing"), "X-Board-Person": "linxia", "X-Board-Actor": "linxia", "X-Board-Via": "web"}
    assert c.get("/api/board/state?person=linxia&view_as=owner", headers=spoof).json()["me"]["id"] == "zhouxing"
    denied = _create(c, spoof, title="冒充负责人立项", line="增长", owner="zhouxing")
    assert denied.status_code == 403 and "团队负责人" in denied.json()["error"]
    ok = _create(c, _bearer("linxia"), title="负责人立的项", line="增长", owner="zhouxing")
    assert ok.status_code == 200 and ok.json()["goal_id"] == 1
    c.post("/api/board/act", headers=_bearer("zhouxing"), json={"action": "start_stage", "params": {"goal_id": 1, "stage": "开发"}})
    c.cookies.clear()
    c.post("/login", data={"token": TOKENS["linxia"]})
    history = c.get("/board/goal/1").text
    assert "周行（经 AI）" in history and "林夏（经 AI）" in history                # 令牌写的记为经 AI
    c.cookies.clear()
    assert c.get("/api/board/state", headers={"Authorization": f"Basic {TOKENS['linxia']}"}).status_code == 401


def test_token_mode_requires_a_token_for_everyone(tmp_path):
    raw = raw_cfg(tmp_path, auth="token")
    raw["people"][1]["token"] = ""
    with pytest.raises(config.ConfigError):
        config.parse_config(raw)


# ---------------------------------------------------------------- owner / member 权限（经接口，令牌身份）

def test_owner_and_member_permissions_follow_roles_not_names(tmp_path):
    c = _app(tmp_path, auth="token")
    lin, zhou, su = _bearer("linxia"), _bearer("zhouxing"), _bearer("suhe")

    def act(who, action, **params):
        return c.post("/api/board/act", headers=who, json={"action": action, "params": params})

    top = _create(c, lin, title="会员订阅上线", line="客户端", owner="zhouxing").json()["goal_id"]
    # 成员：自己负责的目标——记环节、改期、暂停恢复、在下面拆给自己，都行
    assert act(zhou, "start_stage", goal_id=top, stage="开发").status_code == 200
    assert act(zhou, "change_due", goal_id=top, due="2099-01-01", reason="定了").status_code == 200
    assert act(zhou, "pause", goal_id=top, kind="external", note="等审核").status_code == 200
    assert act(zhou, "resume", goal_id=top).status_code == 200
    sub = _create(c, zhou, title="支付回调", owner="zhouxing", parent_id=top)
    assert sub.status_code == 200
    # 成员：新开顶层、拆给别人、换负责人、放弃、换线、改挂 —— 都被拒
    for r in (_create(c, zhou, title="另开一棵", line="增长", owner="zhouxing"),
              _create(c, zhou, title="拆给别人", owner="suhe", parent_id=top),
              act(zhou, "assign", goal_id=top, owner="suhe"),
              act(zhou, "abandon", goal_id=top, reason="不做了"),
              act(zhou, "edit_goal", goal_id=top, line="增长"),
              act(zhou, "edit_goal", goal_id=sub.json()["goal_id"], parent_id="-")):
        assert r.status_code == 403, r.text
    # 别的成员：动不了这个目标；但替负责人做环节时，可以记自己那一段的起止
    assert act(su, "change_due", goal_id=top, due="2099-02-01", reason="x").status_code == 403
    assert act(su, "start_stage", goal_id=top, stage="测试").status_code == 200
    assert act(su, "end_stage", goal_id=top, stage="开发").status_code == 403          # 别人做的段
    assert act(su, "end_stage", goal_id=top, stage="测试").status_code == 200
    # owner 角色：都能做
    assert act(lin, "assign", goal_id=top, owner="suhe").status_code == 200
    assert act(lin, "edit_goal", goal_id=top, line="增长").status_code == 200
    spec = c.get("/api/board/actions", headers=zhou).json()
    assert spec["values"]["roles"] == {"linxia": "owner", "zhouxing": "member", "suhe": "member"}
    assert spec["me"]["role"] == "member" and "团队负责人" in spec["actions"]["assign"]["who"]


def test_several_owners_are_all_team_owners(tmp_path):
    raw = raw_cfg(tmp_path, auth="token")
    raw["people"][2]["role"] = "owner"
    c = TestClient(create_app(config.parse_config(raw)))
    assert _create(c, _bearer("suhe"), title="第二位负责人立的项", line="运营", owner="zhouxing").status_code == 200
    assert _create(c, _bearer("zhouxing"), title="成员立项", line="运营", owner="zhouxing").status_code == 403
    raw["people"] = [dict(p, role="member") for p in raw["people"]]
    with pytest.raises(config.ConfigError):                  # 一个 owner 都没有：启动即拒
        config.parse_config(raw)


def test_member_sees_member_help_and_no_owner_only_forms(tmp_path):
    c = _app(tmp_path, auth="token")
    gid = _create(c, _bearer("linxia"), title="周行的目标", line="增长", owner="zhouxing").json()["goal_id"]
    c.post("/login", data={"token": TOKENS["zhouxing"]})
    index, goal = c.get("/board").text, c.get(f"/board/goal/{gid}").text
    assert "这些只有团队负责人能定" in index and "什么都能录" not in index
    assert "手动修改（备用" in goal and "放弃这个目标" not in goal            # 负责人能改，但放弃只有 owner 角色
    c.cookies.clear()
    c.post("/login", data={"token": TOKENS["suhe"]})
    assert "手动修改（备用" not in c.get(f"/board/goal/{gid}").text            # 不是负责人：没有手动表单
    c.cookies.clear()
    c.post("/login", data={"token": TOKENS["linxia"]})
    owner_goal = c.get(f"/board/goal/{gid}").text
    assert "放弃这个目标" in owner_goal and "什么都能录" in c.get("/board").text
