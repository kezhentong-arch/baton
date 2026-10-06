"""虚构的示例数据（中、英各一套）：只往空库里灌；六个目标各演示一种协作情形，页面上都看得到。"""
import re
from datetime import date

import pytest

from team_board import config, seed
from team_board.board.state import dependency_warnings, fold
from team_board.board.store import connect_board, load_events
from tests.conftest import client_as, raw_cfg

CJK = re.compile(r"[一-鿿]")


def _starter(tmp_path, lang: str) -> dict:
    raw = config.starter_config(lang, data_dir=str(tmp_path / "data"), timezone="America/Los_Angeles")
    return {k: raw[k] for k in ("title", "lang", "people", "lines", "stages", "timezone", "second_timezone", "github")}


def _seeded(tmp_path, lang: str):
    over = _starter(tmp_path, lang)
    owner = over["people"][0]["id"]
    app, c = client_as(tmp_path, owner, **over)
    conn = connect_board(app.state.cfg.data_dir)
    n = seed.seed_demo(conn, lang)
    conn.close()
    return app, c, n


@pytest.mark.parametrize("lang", ["zh", "en"])
def test_seed_builds_the_whole_fictional_board(tmp_path, lang):
    app, c, n = _seeded(tmp_path, lang)
    assert n == 15
    state = c.get("/api/board/state").json()
    goals = {g["gnum"]: g for g in state["goals"]}
    assert sorted(goals) == sorted(["G1", "G1.1", "G1.2", "G1.3", "G2", "G3", "G4", "G4.1", "G4.2", "G4.3", "G5",
                                    "G6", "G6.1", "G6.2", "G6.3"])
    assert not any(g["sample"] for g in state["goals"])               # 灌进去的是普通目标，不标示例
    people = [p.id for p in app.state.cfg.persons]
    owner, m1, m2 = people
    lines, stages = app.state.cfg.lines, app.state.cfg.stages
    BIZ, PRODUCT, UI, DEV, TEST = stages
    cjk = bool(CJK.search(" ".join(g["title"] + g["note"] for g in state["goals"])))
    assert cjk is (lang == "zh")                                      # 两种语言各一套，不混

    # ---- G1：发起人只做业务；执行拆成整包，一块跨到运营线；依赖提前亮黄；下游等依赖暂停 ----
    g1, g11, g12, g13 = goals["G1"], goals["G1.1"], goals["G1.2"], goals["G1.3"]
    assert g1["owner_key"] == owner and [s["stage"] for s in g1["spans"]] == [BIZ] and g1["spans"][0]["end"]
    assert (g11["owner_key"], g12["owner_key"], g13["owner_key"]) == (m1, m2, m2)
    assert g11["line"] == g12["line"] == lines[0] and g13["line"] == lines[2]
    assert g11["current_stages"] == [DEV] and len(g11["due_changes"]) == 1 and g11["latest_due"] > g11["baseline_due"]
    assert [s["stage"] for s in g12["spans"]] == [PRODUCT, UI, PRODUCT, UI]          # 产品与 UI 来回交替
    assert g12["paused_kind"] == "dependency" and g12["pauses"][0]["depends_on"] == g11["id"]
    conn = connect_board(app.state.cfg.data_dir)
    b = fold(load_events(conn))
    conn.close()
    config.use(app.state.cfg)
    from team_board.board.model import utc_now
    deps = {(d.on_goal, d.at_stage) for d in b.goals[g12["id"]].deps}
    assert deps == {(g11["id"], DEV), (g13["id"], TEST)}
    warns = dependency_warnings(b, utc_now())
    assert [(a, on) for a, on, _ in warns] == [(g12["id"], g11["id"])]                # 上游晚于下游需要它的日子
    # ---- G2：一个人全流程，环节重叠、回头再进产品；带来源号 ----
    g2 = goals["G2"]
    assert g2["source"] == f"{app.state.cfg.persons[0].letter}4" and {s["executor"] for s in g2["spans"]} == {owner}
    assert [s["stage"] for s in g2["spans"]] == [BIZ, PRODUCT, UI, DEV, TEST, PRODUCT] and g2["current_stages"] == [DEV, TEST]
    # ---- G3：上周已完成，有做什么 / 做了什么 ----
    g3 = goals["G3"]
    assert g3["status_key"] == "done" and g3["line"] == lines[1] and g3["note"] and g3["done_what"].count("\n") == 2
    # ---- G4：长期负责，负责人自己拆三块给自己；一块已完成，一块改过计划日且已延期 ----
    g4 = goals["G4"]
    assert g4["long_term"] is True and g4["owner_key"] == m1 and g4["baseline_due"] == "" and g4["spans"] == []
    kids = [goals[k] for k in ("G4.1", "G4.2", "G4.3")]
    assert all(k["owner_key"] == m1 and k["parent_id"] == g4["id"] for k in kids)
    assert kids[0]["status_key"] == "done" and kids[1]["due_changes"] and kids[1]["delay_days"] >= 1 and kids[1]["delay_text"]
    conn = connect_board(app.state.cfg.data_dir)
    creators = {int(e.subject[5:]): e.actor for e in load_events(conn) if e.kind == "goal.proposed"}
    conn.close()
    assert {creators[k["id"]] for k in kids} == {m1} and creators[g4["id"]] == owner   # 子块是他自己拆的，母题是 owner 立的
    # ---- G5：笼统的事，不拆环节 ----
    assert goals["G5"]["spans"] == [] and goals["G5"]["line"] == lines[3] and goals["G5"]["status_key"] == "active"
    # ---- G6：拆三块——整包给别人（已完成）、不用等谁（已完成，测试期间回头改产品）、要等依赖（暂停→恢复→开发、测试、再开发） ----
    g6, c_, a_, b_ = goals["G6"], goals["G6.1"], goals["G6.2"], goals["G6.3"]
    assert [s["stage"] for s in g6["spans"]] == [BIZ] and g6["delay_days"] > 0 and g6["status_key"] == "active"
    assert c_["owner_key"] == m1 and c_["status_key"] == "done" and [s["stage"] for s in c_["spans"]] == [PRODUCT, DEV, TEST]
    assert a_["owner_key"] == owner and a_["status_key"] == "done"
    assert [s["stage"] for s in a_["spans"]] == [PRODUCT, UI, DEV, TEST, PRODUCT]
    assert b_["owner_key"] == owner and [s["stage"] for s in b_["spans"]] == [PRODUCT, DEV, TEST, DEV]
    assert b_["current_stages"] == [TEST, DEV] and b_["delay_days"] > 0
    pause, = b_["pauses"]
    assert pause["kind_key"] == "dependency" and pause["depends_on"] == c_["id"] and pause["end"] == c_["done_at"]
    assert b_["pause_days"]["dependency"] == 12.0
    # ---- 口述：一条已录入、两条待录入 ----
    notes = state["notes"]
    assert [x["done"] for x in sorted(notes, key=lambda x: x["id"])] == [True, False, False]
    assert {x["who_key"] for x in notes} == {owner, m1, m2}


@pytest.mark.parametrize("lang, texts", [
    ("zh", ["会员订阅上线", "支付与订阅后端", "会员页面：从产品到测试", "后台价格配置", "新用户引导改版", "宠物医院合作落地页",
            "崩溃率降到 0.5% 以下", "新协作方式落地", "智能喂养提醒 1.0", "依赖冲突", "等依赖", "被拖住", "延期", "长期"]),
    ("en", ["Launch paid membership", "Payments &amp; subscription backend", "Membership screens, product to test",
            "Admin pricing settings", "New-user onboarding redesign", "Vet-clinic partner landing page", "Crash rate under 0.5%",
            "Roll out the new way of working", "Smart feeding reminders 1.0", "Dependency at risk", "Waiting on a dependency",
            "Held up", "Late", "Ongoing"]),
])
def test_seeded_scenarios_are_visible_on_the_pages(tmp_path, lang, texts):
    app, c, _n = _seeded(tmp_path, lang)
    page = c.get("/board")
    assert page.status_code == 200
    for text in texts:
        assert text in page.text, text
    other = CJK.search(page.text) if lang == "en" else None
    assert other is None
    cfg = app.state.cfg
    ops = page.text.split(f'data-key="L:{cfg.lines[2]}"')[1].split("<section")[0]
    assert cfg.lines[2] != cfg.lines[0] and 'data-fam="G1"' in ops and "bd-belongs" in ops       # 跨线的那块在运营线，写着属于 G1
    assert page.text.count('data-fam="G1"') == 4                                                # 一家四块共用底色
    assert "bd-src" in page.text and f"· {cfg.persons[0].letter}4</span>" in page.text          # G2 行上的来源号
    assert "bd-end-done" in page.text or 'data-ended="done"' in page.text
    for gid in range(1, 16):
        r = c.get(f"/board/goal/{gid}")
        assert r.status_code == 200, gid
        assert lang == "zh" or not CJK.search(r.text), gid
    # 没人标示例，所以没有「看示例看板」入口；示例看板页本身照常能开（只是没有示例案例）
    assert "/board/sample" not in page.text and c.get("/board/sample").status_code == 200
    # 练手看板 = 正式库的副本
    practice = c.get("/board/practice")
    assert practice.status_code == 200 and texts[0] in practice.text and (lang == "zh" or not CJK.search(practice.text))
    assert len(c.get("/api/board/practice/state").json()["goals"]) == 15


def test_seed_only_goes_into_an_empty_board_and_dates_follow_the_seeding_day(tmp_path):
    cfg = config.use(config.parse_config(raw_cfg(tmp_path)))
    conn = connect_board(tmp_path / "b")
    assert seed.seed_demo(conn, "zh", today=date(2025, 3, 15)) == 15
    b = fold(load_events(conn))
    g3 = next(g for g in b.goals.values() if g.status == "done" and g.parent_id is None)
    assert str(g3.baseline_due) == "2025-03-09" and g3.done_at.astimezone(cfg.tz).date() == date(2025, 3, 8)   # 往前推 16 天立项，第 9 天完成
    assert max(e.occurred_at for e in load_events(conn)).astimezone(cfg.tz).date() < date(2025, 3, 15)        # 最晚的一步也在「今天」之前
    assert not any(e.backfill for e in load_events(conn)) and {e.via for e in load_events(conn)} == {"seed"}
    with pytest.raises(seed.SeedRefused):                  # 已经有目标了：不重复灌
        seed.seed_demo(conn, "en")
    assert len(fold(load_events(conn)).goals) == 15
    conn.close()


def test_seed_works_with_any_team_shape(tmp_path):
    """人、线、环节取配置里的：只有一个人、两条线、三个环节也灌得进去（按顺序取，不够就复用）。"""
    cfg = config.use(config.parse_config(raw_cfg(
        tmp_path, people=[{"id": "solo", "name": "独行", "letter": "D", "role": "owner", "token": "x"}],
        lines=["甲线", "乙线"], stages=["想", "做", "验"], github={"enabled": False})))
    conn = connect_board(cfg.data_dir)
    assert seed.seed_demo(conn, "zh") == 15
    b = fold(load_events(conn))
    assert {g.owner for g in b.goals.values()} == {"solo"} and {g.line for g in b.goals.values()} <= {"甲线", "乙线"}
    conn.close()
