"""首页标完成、版本行按挂它的目标归线、详情页显示版本、接口给各个时刻、计划到小时、练手看板、时间线细节。"""
from team_board.board.store import connect_board
from tests.conftest import client_as as _client

WEB = "acme/web"
APP = "acme/app"


def _milestone(app, repo, number, title, closed_at=None):
    conn = connect_board(app.state.cfg.data_dir)
    conn.execute("INSERT OR REPLACE INTO gh_milestones(repo, number, title, state, due_on, created_at, closed_at)"
                 " VALUES(?,?,?,?,?,?,?)",
                 (repo, number, title, "CLOSED" if closed_at else "OPEN", None, "2026-09-28T00:00:00+00:00", closed_at))
    conn.commit()
    conn.close()


def _act(c, action, **params):
    r = c.post("/api/board/act", json={"action": action, "params": params})
    assert r.status_code == 200, r.text
    return r.json()


def _band(page: str, line: str) -> str:
    """首页里某条线那一段 HTML（从线标题到下一条线标题）。"""
    i = page.index(f"</span>{line}</b>")
    j = page.find("<section class=\"bd-band", i)
    return page[i:j if j > 0 else None]


def test_index_marks_done_and_abandoned_goals(tmp_path):
    _app, c = _client(tmp_path)
    a = _act(c, "create", title="做完的事", line="管理与协作", owner="linxia", due="2026-10-05",
             occurred_at="2026-09-28T10:00:00-07:00")["goal_id"]
    b = _act(c, "create", title="放弃的事", line="管理与协作", owner="linxia",
             occurred_at="2026-09-28T10:00:00-07:00")["goal_id"]
    _act(c, "complete", goal_id=a, occurred_at="2026-10-01T22:40:00-07:00")
    _act(c, "abandon", goal_id=b, reason="不做了", occurred_at="2026-10-01T09:00:00-07:00")
    page = c.get("/board").text
    assert "已完成 10-01" in page and "bd-end-done" in page and "✓" in page
    assert "已放弃 10-01" in page and "bd-end-abandoned" in page
    # 行上带着内容范围与结束标记，浏览器据此按窗口决定要不要显示
    assert 'data-span="' in page and 'data-ended="done"' in page and 'data-ended="abandoned"' in page
    goal = c.get(f"/board/goal/{a}").text
    assert "已完成 10-01 22:40" in goal


def test_version_row_sits_on_the_line_of_the_goal_that_carries_it(tmp_path):
    app, c = _client(tmp_path)
    _milestone(app, WEB, 1, "工程进度看板 v1.0")
    _milestone(app, APP, 9, "v3.7")
    top = _act(c, "create", title="新协作模式落地", line="管理与协作", owner="linxia")["goal_id"]
    _act(c, "create", title="团队进度看板", parent_id=top, owner="linxia", version=f"{WEB}#1")
    _act(c, "create", title="看板录入手册", parent_id=top, owner="zhouxing", version=f"{WEB}#1")   # v1.2：装着两个目标才成行
    _act(c, "track_version", ref=f"{APP}#9")         # 没有目标挂的版本：仍按仓库归线（客户端）
    page = c.get("/board").text
    assert ">版本 工程进度看板 v1.0</a>" in _band(page, "管理与协作")
    assert "工程进度看板 v1.0" not in _band(page, "增长")
    assert ">版本 v3.7</a>" in _band(page, "客户端")
    # 版本行写挂它的目标的负责人（里程碑本身没有负责人）；没目标挂的版本没人可写
    mgmt = _band(page, "管理与协作")
    vrow = mgmt[mgmt.index(">版本 工程进度看板 v1.0</a>"):mgmt.index("G1</span>")]
    assert "挂在这个版本下的目标的负责人" in vrow and ">林夏</span>" in vrow and ">周行</span>" in vrow
    crow = _band(page, "客户端")
    assert "挂在这个版本下的目标的负责人" not in crow
    # 版本牌只在挂上来的那一层：子目标有、顶层没有
    assert mgmt.count('class="bd-vn"') == 2 and ">工程进度看板 v1.0</a>" in mgmt


def test_version_carrying_one_goal_is_a_badge_not_a_row(tmp_path):
    """版本只挂一个目标时不单独成行——那只是目标行的复读，目标行上的小牌子就够了；
    挂两个以上目标、或没挂任何目标的版本才成行，成行就列出装了哪些目标、点一下进那个目标。"""
    app, c = _client(tmp_path)
    _milestone(app, WEB, 4, "Issue 协作规范 v1.0")
    _milestone(app, WEB, 6, "工程进度看板 v1.1")
    _milestone(app, APP, 9, "v3.7")
    top = _act(c, "create", title="新协作模式落地", line="管理与协作", owner="linxia")["goal_id"]
    one = _act(c, "create", title="Git Issue 流转更新", parent_id=top, owner="linxia", version=f"{WEB}#4")["goal_id"]
    _act(c, "create", title="流转更新的子块", parent_id=one, owner="zhouxing")      # 继承上层的版本，不算第二个目标
    a = _act(c, "create", title="团队进度看板 v1.1", parent_id=top, owner="linxia", version=f"{WEB}#6")["goal_id"]
    b = _act(c, "create", title="看板站运维手册", line="增长", owner="zhouxing", version=f"{WEB}#6")["goal_id"]
    _act(c, "track_version", ref=f"{APP}#9")
    page = c.get("/board").text
    mgmt = _band(page, "管理与协作")
    assert ">版本 Issue 协作规范 v1.0</a>" not in page                       # 一对一：不成行
    assert ">Issue 协作规范 v1.0</a>" in mgmt and 'class="bd-vn"' in mgmt     # 目标行上的牌子还在
    # 两个目标：成行，挂的目标分在两条线就两条线各一次；行上列出装着的目标并能点进去
    assert ">版本 工程进度看板 v1.1</a>" in mgmt and ">版本 工程进度看板 v1.1</a>" in _band(page, "增长")
    vrow = mgmt[mgmt.index(">版本 工程进度看板 v1.1</a>"):mgmt.index("G1</span>")]
    assert f'href="/board/goal/{a}"><span class="bd-gid">G1.2</span> 团队进度看板 v1.1</a>' in vrow
    assert f'href="/board/goal/{b}"><span class="bd-gid">G{b}</span> 看板站运维手册</a>' in vrow     # 顶层目标的编号就是它的 id
    assert "装着" in vrow
    # 没挂任何目标：照旧成行，只显示版本名
    crow = _band(page, "客户端")
    assert ">版本 v3.7</a>" in crow and "装着" not in crow


def test_goal_page_shows_version_by_name_and_history_uses_names(tmp_path):
    app, c = _client(tmp_path)
    _milestone(app, WEB, 1, "工程进度看板 v1.0")
    gid = _act(c, "create", title="看板", line="管理与协作", owner="linxia", version=f"{WEB}#1")["goal_id"]
    _act(c, "edit_goal", goal_id=gid, version="-")
    _act(c, "edit_goal", goal_id=gid, version=f"{WEB}#1")
    page = c.get(f"/board/goal/{gid}").text
    assert 'class="bd-tag bd-tag-ver"' in page and "版本 工程进度看板 v1.0" in page
    assert "/board/version?repo=acme/web&amp;number=1" in page
    assert "版本改为 「工程进度看板 v1.0」" in page and "挂在版本 「工程进度看板 v1.0」 下" in page
    assert "版本改为 acme/web#1" not in page
    ver = c.get(f"/board/version?repo={WEB}&number=1").text
    assert "进行中" in ver and "G1" in ver


def test_state_api_gives_moments_spans_pauses_and_version(tmp_path):
    app, c = _client(tmp_path)
    _milestone(app, WEB, 2, "林夏的个人看板 v1.0", closed_at="2026-10-02T12:36:03+00:00")
    gid = _act(c, "create", title="个人看板", line="管理与协作", owner="linxia", version=f"{WEB}#2",
               occurred_at="2026-10-01T22:50:00-07:00")["goal_id"]
    _act(c, "start_stage", goal_id=gid, stage="开发", occurred_at="2026-10-02T01:10:00-07:00")
    _act(c, "pause", goal_id=gid, kind="external", note="等机器", occurred_at="2026-10-02T02:00:00-07:00")
    _act(c, "resume", goal_id=gid, occurred_at="2026-10-02T02:30:00-07:00")
    _act(c, "end_stage", goal_id=gid, stage="开发", occurred_at="2026-10-02T05:36:00-07:00")
    _act(c, "complete", goal_id=gid, occurred_at="2026-10-02T05:36:53-07:00")
    _act(c, "track_version", ref=f"{WEB}#2")
    d = c.get("/api/board/state").json()
    g = next(x for x in d["goals"] if x["id"] == gid)
    assert g["approved_at"] == "2026-10-02T05:50:00+00:00"
    assert g["done_at"] == "2026-10-02T12:36:53+00:00" and g["abandoned_at"] == ""
    assert g["spans"] == [{"stage": "开发", "executor": "linxia", "start": "2026-10-02T08:10:00+00:00",
                           "end": "2026-10-02T12:36:00+00:00"}]
    assert g["pauses"][0]["kind"] == "等外部" and g["pauses"][0]["end"] == "2026-10-02T09:30:00+00:00"
    assert g["version"] == {"ref": f"{WEB}#2", "name": "林夏的个人看板 v1.0"}
    # GitHub 上关闭了的里程碑，看板没手动标也算完成，时刻取关闭时刻
    v = d["versions"][f"{WEB}#2"]
    assert v["done"] is True and v["done_at"] == "2026-10-02T12:36:03+00:00" and v["name"] == "林夏的个人看板 v1.0"
    assert "已完成 10-02" in c.get("/board").text


# ---- 计划完成到小时 ----

def test_due_parses_day_to_end_of_day_and_time_to_that_hour():
    from team_board.board.model import Due
    d = Due.parse("2026-10-02")
    assert str(d) == "2026-10-02" and d.short == "10-02" and d.at.isoformat() == "2026-10-02T23:59:59-07:00"
    t = Due.parse("2026-10-02 08:00")
    assert str(t) == "2026-10-02 08:00" and t.short == "10-02 08:00" and t.at.isoformat() == "2026-10-02T08:00:00-07:00"
    assert str(Due.parse("2026-10-02T08:00")) == "2026-10-02 08:00"
    assert t < d
    import pytest
    with pytest.raises(ValueError):
        Due.parse("2026-10-02 8am")


def test_hourly_due_shows_on_pages_and_delay_counts_hours(tmp_path, monkeypatch):
    from datetime import datetime, timezone
    from team_board.board import routes, view
    _app, c = _client(tmp_path)
    gid = _act(c, "create", title="看板 v1.1", line="管理与协作", owner="linxia", due="2026-10-02",
               occurred_at="2026-10-01T22:50:00-07:00")["goal_id"]
    _act(c, "change_due", goal_id=gid, due="2026-10-02T08:00", reason="定的是周五上午 8 点前",
         occurred_at="2026-10-02T05:35:00-07:00")
    bad = c.post("/api/board/act", json={"action": "change_due", "params": {
        "goal_id": gid, "due": "2026-10-02 08:00", "reason": "一样的"}})
    assert bad.status_code == 409 and "一样" in bad.json()["error"]
    g = next(x for x in c.get("/api/board/state").json()["goals"] if x["id"] == gid)
    assert g["latest_due"] == "2026-10-02 08:00" and g["baseline_due"] == "2026-10-02"
    page = c.get("/board?zoom=day").text
    assert "改到 10-02 08:00" in page and "计划 10-02 08:00（原定 10-02）" in page
    assert "zoom-day" in page and ">02:00</span>" in page and "选一天" in page
    # 延期按小时：现在是洛杉矶 10-02 11:30，超出基准（10-02 23:59）还没到 → 不延期；把基准当成 08:00，超出 3 小时半写 4 小时（四舍五入，同个人看板）
    fixed = datetime(2026, 10, 2, 18, 30, tzinfo=timezone.utc)      # 洛杉矶 11:30
    monkeypatch.setattr(routes, "utc_now", lambda: fixed)
    assert next(x for x in c.get("/api/board/state").json()["goals"] if x["id"] == gid)["delay_text"] == ""
    g2 = _act(c, "create", title="八点前的事", line="管理与协作", owner="linxia", due="2026-10-02 08:00",
              occurred_at="2026-10-01T22:50:00-07:00")["goal_id"]
    d = c.get("/api/board/state").json()
    me = next(x for x in d["goals"] if x["id"] == g2)
    assert me["delay_text"] == "4 小时" and me["delay_days"] == 0.15     # 实际超出多久，不再向上取整成 1 天
    assert any(b["text"].endswith("已超出计划 4 小时") for b in d["blockers"])
    assert "延期 4 小时" in c.get("/board").text
    goal = c.get(f"/board/goal/{g2}").text
    assert "已超出 4 小时" in goal and "计划 2026-10-02 08:00 完成" in goal


# ---- 练手看板：数据完全隔离、可重置 ----

def test_practice_board_is_a_separate_copy_that_resets(tmp_path):
    app, c = _client(tmp_path)
    real = _act(c, "create", title="真的事", line="客户端", owner="linxia")["goal_id"]
    page = c.get("/board/practice")
    assert page.status_code == 200 and "练手看板" in page.text and "重置练手数据" in page.text
    assert "真的事" in page.text                                  # 练手库 = 此刻正式数据的副本
    assert (app.state.cfg.data_dir / "board" / "practice.sqlite").exists()
    r = c.post("/api/board/practice/act", json={"action": "create", "params": {
        "title": "练手立的项", "line": "运营", "owner": "linxia", "due": "2026-10-09 18:00"}})
    assert r.status_code == 200 and r.json()["ok"]
    assert "练手立的项" in c.get("/board/practice").text
    assert "练手立的项" not in c.get("/board").text                # 正式看板看不到练手的事
    assert all(g["title"] != "练手立的项" for g in c.get("/api/board/state").json()["goals"])
    assert c.get("/api/board/practice/state").json()["practice"] is True
    # 练手页里的链接和表单都留在练手这边
    gp = c.get(f"/board/practice/goal/{real}").text
    assert 'action="/board/practice/act"' in gp and "← 回练手看板" in gp and '/api/board/practice' in gp
    assert 'href="/board/goal/' not in c.get("/board/practice").text
    # 重置 = 回到此刻正式数据
    _act(c, "create", title="重置后才有的事", line="客户端", owner="linxia")
    r = c.post("/board/practice/reset", follow_redirects=False)
    assert r.status_code == 303 and "/board/practice" in r.headers["location"]
    page = c.get("/board/practice").text
    assert "练手立的项" not in page and "重置后才有的事" in page


def test_practice_page_copies_a_practice_prompt_for_ai(tmp_path):
    """练手看板的口述框复制给 AI 的话要说清是练手，AI 才会全程走练手看板、不碰正式看板。"""
    _app, c = _client(tmp_path)
    gid = _act(c, "create", title="真的事", line="客户端", owner="linxia")["goal_id"]
    real, prac = c.get("/board").text, c.get("/board/practice").text
    assert "var PRACTICE = true;" in prac and "录进练手看板（练手口述 #" in prac
    assert "practice=true" in prac and "不要碰正式看板" in prac and "不要推进个人看板" in prac
    assert "var PRACTICE = false;" in real and "录进团队看板（口述 #" in real     # 两段话都在脚本里，开关决定复制哪段
    # 练手的目标详情页同样说练手；正式的照旧
    assert "var PRACTICE = true;" in c.get(f"/board/practice/goal/{gid}").text
    assert "var PRACTICE = false;" in c.get(f"/board/goal/{gid}").text


def test_rows_always_show_who_else_is_involved_and_light_up_me(tmp_path):
    """看板为协作而设，母任务和子任务都要一直看得见负责人以外还涉及谁，看板的人自己那块点亮。"""
    _app, c = _client(tmp_path)
    top = _act(c, "create", title="新协作模式落地", line="管理与协作", owner="linxia")["goal_id"]
    sub = _act(c, "create", title="周行的个人看板", parent_id=top, owner="zhouxing")["goal_id"]
    _act(c, "start_stage", goal_id=sub, stage="测试", executor="suhe")
    page = c.get("/board").text
    mgmt = _band(page, "管理与协作")
    top_row = mgmt[mgmt.index("新协作模式落地"):mgmt.index("周行的个人看板")]
    assert "负责人以外还涉及：周行、苏禾" in top_row and ">周行</span>" in top_row and ">苏禾</span>" in top_row
    assert 'class="bd-who bd-me"' in top_row                      # 看板的人是林夏：自己那块点亮
    sub_row = mgmt[mgmt.index("周行的个人看板"):]
    assert "负责人以外还涉及：苏禾" in sub_row and "bd-me" not in sub_row
    # 苏禾看：她做的那段在子任务上点亮
    _app2, l2 = _client(tmp_path, "suhe")
    page2 = l2.get("/board").text
    sub_row2 = page2[page2.index("周行的个人看板"):]
    assert 'class="bd-who bd-me"' in sub_row2


# ---- 时间线：没做完的事往后画虚线；拖到过去时还没立项的不出现 ----

def _row(band: str, title: str) -> str:
    """某个目标那一行的 HTML：从它的行元素开头到下一行开头（行的先后由看板排，不依赖立项顺序）。"""
    i = band.rindex('<div class="bd-row', 0, band.index(title))
    j = band.find('<div class="bd-row', i + 1)
    return band[i:j if j > 0 else None]


def test_unfinished_goals_continue_as_dashed_future_lines(tmp_path):
    """拖到未来：没做完的目标往后画淡虚线「还在做」——开着的环节同色、没分环节灰、眼下没环节开着的在寿命线位置灰虚线；
    做完的不画。图例加「还在做」。"""
    app, c = _client(tmp_path)
    _milestone(app, WEB, 6, "工程进度看板 v1.1")
    _milestone(app, WEB, 2, "林夏的个人看板 v1.0", closed_at="2026-10-02T12:36:03+00:00")
    _act(c, "track_version", ref=f"{WEB}#6")
    _act(c, "track_version", ref=f"{WEB}#2")
    _act(c, "complete_version", ref=f"{WEB}#2")
    doing = _act(c, "create", title="开发中的事", line="管理与协作", owner="linxia")["goal_id"]
    _act(c, "start_stage", goal_id=doing, stage="开发")
    plain = _act(c, "create", title="没分环节的事", line="管理与协作", owner="linxia")["goal_id"]
    waiting = _act(c, "create", title="等别人的事", line="管理与协作", owner="linxia",
                   occurred_at="2026-10-01T08:00:00-07:00")["goal_id"]
    _act(c, "start_stage", goal_id=waiting, stage="产品", occurred_at="2026-10-01T09:00:00-07:00")
    _act(c, "end_stage", goal_id=waiting, stage="产品", occurred_at="2026-10-01T10:00:00-07:00")
    done = _act(c, "create", title="做完的事", line="管理与协作", owner="linxia",
                occurred_at="2026-10-01T08:00:00-07:00")["goal_id"]
    _act(c, "start_stage", goal_id=done, stage="开发", occurred_at="2026-10-01T09:00:00-07:00")
    _act(c, "complete", goal_id=done)
    page = c.get("/board").text
    mgmt = _band(page, "管理与协作")
    r1 = _row(mgmt, "开发中的事")
    assert 'class="bd-future"' in r1 and "border-color:var(--st3)" in r1 and "还在做：开发（林夏）进行中" in r1
    r2 = _row(mgmt, "没分环节的事")
    assert 'class="bd-future"' in r2 and "border-color:var(--ver)" in r2 and "还在做（没分环节）" in r2
    r3 = _row(mgmt, "等别人的事")
    assert 'class="bd-life bd-life-future"' in r3 and 'class="bd-future"' not in r3
    r4 = _row(mgmt, "做完的事")
    assert "bd-future" not in r4
    # 版本：没发布的接灰虚线，发布了的不接
    assert "版本 工程进度看板 v1.1：还在做" in page and "林夏的个人看板 v1.0：还在做" not in page
    assert "虚线「还在做」" in page                               # 图例


def test_rows_carry_span_so_browser_hides_goals_not_yet_approved_when_dragged_to_the_past(tmp_path):
    """拖到过去：那时还没立项的目标不出现——每行（不只已结束的）都带 data-span，浏览器按窗口筛；
    进行中的只看立项点（span 起点），已结束的看起止。"""
    _app, c = _client(tmp_path)
    _act(c, "create", title="十月才立的事", line="管理与协作", owner="linxia", occurred_at="2026-10-01T09:00:00-07:00")
    page = c.get("/board").text
    row = _row(_band(page, "管理与协作"), "十月才立的事")
    assert 'data-span="' in row and "data-ended" not in row
    # 浏览器那边的规则就在页面脚本里：进行中的只比立项点
    assert "if (!r.dataset.ended) { return +sp[0] > win[1]; }" in page


def test_rows_grow_with_label_content_and_horizontal_drag_does_not_leave_the_page(tmp_path):
    """核验：名称折两行再带小牌子的行，名字下面那行被下一行压住只露半截；横向拖时间线会触发浏览器返回。
    行高只给下限（min-height），名称列内容多就撑高；整页与滚动容器都关掉横向越界。"""
    app, c = _client(tmp_path)
    _milestone(app, WEB, 8, "工程进度看板 v1.2")
    gid = _act(c, "create", title="团队进度看板 v1.2", line="管理与协作", owner="linxia", version=f"{WEB}#8")["goal_id"]
    page = c.get("/board").text
    band = _band(page, "管理与协作")
    row = band[band.rindex('<div class="bd-row', 0, band.index("团队进度看板 v1.2")):band.index("团队进度看板 v1.2")]
    assert 'style="min-height:' in row and 'style="height:' not in row
    assert "overscroll-behavior-x:contain" in page
    # 整页关掉横向越界只在首页（详情页、版本页没法左右滑动返回首页）
    for url in ("/board", "/board/practice", "/board/sample"):
        assert "html{overscroll-behavior-x:none}" in c.get(url).text, url
    for url in (f"/board/goal/{gid}", f"/board/practice/goal/{gid}",
                f"/board/version?repo={WEB}&number=8", f"/board/practice/version?repo={WEB}&number=8"):
        r = c.get(url)
        assert r.status_code == 200 and "overscroll-behavior-x:none" not in r.text, url


# ---- 时长写法、同级排序、练手页页头 ----

def test_duration_text_writes_minutes_hours_then_days():
    """不满 1 小时写分钟、不满 1 天写小时、满 1 天写天；小时和天一位小数，整数不带「.0」。"""
    from datetime import datetime, timedelta
    from team_board.board.model import duration_text
    assert duration_text(timedelta(0)) == "不到 1 分钟"
    assert duration_text(timedelta(minutes=12)) == "12 分钟"
    assert duration_text(timedelta(minutes=59, seconds=59)) == "59 分钟"
    assert duration_text(timedelta(hours=1)) == "1 小时"
    assert duration_text(timedelta(minutes=80)) == "1.3 小时"
    assert duration_text(timedelta(days=1)) == "1 天"
    assert duration_text(timedelta(hours=36)) == "1.5 天"


def test_goal_page_writes_short_stages_in_minutes_not_zero_days(tmp_path, monkeypatch):
    """一个真实出现过的情形：产品 12 分钟、开发 57 分钟、测试 49 分钟，详情页原来三段都写「0.0 天」。"""
    from datetime import datetime, timezone
    from team_board.board import routes
    _app, c = _client(tmp_path)
    monkeypatch.setattr(routes, "utc_now", lambda: datetime(2026, 10, 2, 18, 30, tzinfo=timezone.utc))   # 洛杉矶 11:30
    gid = _act(c, "create", title="看板 v1.2", line="管理与协作", owner="linxia", due="2026-10-02 12:00",
               occurred_at="2026-10-02T08:40:00-07:00")["goal_id"]
    for action, stage, at in (("start_stage", "产品", "08:40"), ("end_stage", "产品", "08:52"),
                              ("start_stage", "开发", "08:57"), ("start_stage", "测试", "09:05"),
                              ("end_stage", "开发", "09:54"), ("end_stage", "测试", "09:54")):
        _act(c, action, goal_id=gid, stage=stage, occurred_at=f"2026-10-02T{at}:00-07:00")
    _act(c, "complete", goal_id=gid, occurred_at="2026-10-02T10:00:00-07:00")
    page = c.get(f"/board/goal/{gid}").text
    assert "产品 12 分钟" in page and "开发 57 分钟" in page and "测试 49 分钟" in page
    assert "已 1.3 小时" in page and "0.0 天" not in page and " 天" not in page.split("<h3>环节</h3>")[1].split("</div>")[0]
    # 接口里的天数照旧是数字（个人看板等在读）
    g = next(x for x in c.get("/api/board/state").json()["goals"] if x["id"] == gid)
    assert g["stage_days"]["开发"] == 0.0


def test_doing_list_writes_delay_unit_once(tmp_path, monkeypatch):
    """「现在在做什么」的延期：延期文字自带单位（3 小时 / 2 天），模板原来又加了个「天」→「已超出 3 小时 天」。"""
    from datetime import datetime, timezone
    from team_board.board import routes
    _app, c = _client(tmp_path)
    monkeypatch.setattr(routes, "utc_now", lambda: datetime(2026, 10, 2, 18, 30, tzinfo=timezone.utc))   # 洛杉矶 11:30
    _act(c, "create", title="八点前的事", line="管理与协作", owner="linxia", due="2026-10-02 08:00",
         occurred_at="2026-10-01T22:50:00-07:00")
    doing = c.get("/board").text.split('id="bd-doing"')[1]
    assert "已超出 4 小时</span>" in doing and "小时 天" not in doing


def test_blocks_under_one_parent_sort_by_number(tmp_path):
    """号按录进团队看板的先后发，以前同一上层下按立项时间排：先在个人看板立、收尾才推上来的块（05:55 立项、第 10 号）
    排到了第 9 号块（08:40 立项）上面。改成按编号排，9 在 10 上面（也防按字符串排成 10 在 9 前）。"""
    _app, c = _client(tmp_path)
    top = _act(c, "create", title="母题", line="管理与协作", owner="linxia",
               occurred_at="2026-10-01T04:46:00-07:00")["goal_id"]
    kids = [_act(c, "create", title=f"块{i}", owner="linxia", parent_id=top,
                 occurred_at=f"2026-10-02T08:{i:02d}:00-07:00")["goal_id"] for i in range(1, 10)]
    late_push = _act(c, "create", title="个人看板先立的块", owner="linxia", parent_id=top,
                     occurred_at="2026-10-02T05:55:00-07:00")["goal_id"]
    nums = {g["id"]: g["gnum"] for g in c.get("/api/board/state").json()["goals"]}
    assert nums[kids[8]] == f"G{top}.9" and nums[late_push] == f"G{top}.10"
    band = _band(c.get("/board").text, "管理与协作")
    order = [band.index(f'bd-gid">G{top}.{n}<') for n in range(1, 11)]
    assert order == sorted(order)
    detail = c.get(f"/board/goal/{top}").text.split("拆出来的子目标")[1]
    assert detail.index(f">G{top}.9<") < detail.index(f">G{top}.10<")


def test_practice_header_says_when_it_was_reset_instead_of_sync_alarms(tmp_path, monkeypatch):
    """练手库是重置那一刻的副本、从不同步：页头不再亮「已超过 30 分钟没有更新」「上次同步失败」，改说几点重置的。"""
    from datetime import datetime, timezone
    from team_board.board import store
    app, c = _client(tmp_path)
    conn = connect_board(app.state.cfg.data_dir)
    conn.execute("INSERT INTO gh_sync_runs(started_at, finished_at, ok, error) VALUES(?,?,0,?)",
                 ("2026-10-02T14:00:00+00:00", "2026-10-02T14:00:05+00:00", "GitHub 返回 HTTP 502"))
    conn.commit()
    conn.close()
    real = c.get("/board").text
    assert "已超过 30 分钟没有更新" in real and "上次同步失败" in real            # 正式看板照旧提醒
    monkeypatch.setattr(store, "utc_now", lambda: datetime(2026, 10, 2, 14, 4, tzinfo=timezone.utc))   # 洛杉矶 07:04
    assert c.post("/board/practice/reset", follow_redirects=False).status_code == 303
    prac = c.get("/board/practice").text
    head = prac.split('<div class="bd-head">')[1].split("</div>")[0]
    assert "练手数据是 10-02 07:04（洛杉矶）重置的，GitHub 数据停在那一刻、不再更新" in head
    assert "已超过 30 分钟" not in prac and "上次同步失败" not in prac and "GitHub 数据截至" not in prac
    # 很早以前建的练手库没记重置时刻：照样不亮提醒，只说「上次重置」
    pconn = connect_board(app.state.cfg.data_dir, practice=True)
    pconn.execute("DROP TABLE practice_meta")
    pconn.commit()
    pconn.close()
    assert "练手数据是上次重置时复制的" in c.get("/board/practice").text


def test_late_text_counts_actual_overrun_like_personal_board():
    """延期按实际超出多久，和个人看板 lateText 一字不差：G1 计划 09-20，洛杉矶 10-03 00:40 看，
    超出 12 天 41 分钟，原来向上取整写 13 天、个人看板写 12 天。逢五进一同 JS（Python 的 round 逢五取偶，1.25 天会写成 1.2）。"""
    from datetime import datetime, timedelta

    from team_board.board.model import Due, late_text, tz
    LA = tz()
    g1 = Due.parse("2026-09-20").at                                    # 只写日期 = 当天 23:59:59
    assert late_text(g1, datetime(2026, 10, 3, 0, 40, tzinfo=LA)) == "12 天"
    t0 = datetime(2026, 10, 1, 8, 0, tzinfo=LA)
    cases = {timedelta(minutes=59): "", timedelta(hours=3, minutes=29): "3 小时", timedelta(hours=23, minutes=40): "24 小时",
             timedelta(days=1): "1.0 天", timedelta(hours=30): "1.3 天", timedelta(days=2, hours=12): "2.5 天",
             timedelta(days=9, hours=23): "10.0 天", timedelta(days=10, hours=11): "10 天", timedelta(days=10, hours=12): "11 天",
             # 逢五按浮点精确值进位（）：1.15 天的浮点是 1.1499…，JS 写 1.1；乘 10 再进位会错写成 1.2
             timedelta(hours=27, minutes=36): "1.1 天", timedelta(days=9, hours=22, minutes=48): "9.9 天"}
    for late, want in cases.items():
        assert late_text(t0, t0 + late) == want, (late, want)


def test_linkify_keeps_text_escaped_and_only_links_http():
    """网址成链接、其余照旧转义；句读和多出来的右括号不算网址，javascript: 永远不成链接。"""
    from team_board.templating import linkify

    def a(u):
        return f'<a href="{u}" target="_blank" rel="noopener">{u}</a>'
    cases = {
        "见 https://x.com/a.": f"见 {a('https://x.com/a')}.",
        "（https://x.com/a）": f"（{a('https://x.com/a')}）",
        "(see https://en.wikipedia.org/wiki/A_(b))": f"(see {a('https://en.wikipedia.org/wiki/A_(b)')})",
        "https://x.com/?a=1&b=2，下一句": '<a href="https://x.com/?a=1&amp;b=2" target="_blank" rel="noopener">'
                                       'https://x.com/?a=1&amp;b=2</a>，下一句',
        "两个 http://a.cn/1 和 https://b.cn/2": f"两个 {a('http://a.cn/1')} 和 {a('https://b.cn/2')}",
        "<b>粗</b> javascript:alert(1) https://": "&lt;b&gt;粗&lt;/b&gt; javascript:alert(1) https://",
        "https://x.com/\"onmouseover=\"x": '<a href="https://x.com/" target="_blank" rel="noopener">https://x.com/</a>'
                                         '&#34;onmouseover=&#34;x',
        "没有网址": "没有网址",
        "": "",
    }
    for raw, want in cases.items():
        assert str(linkify(raw)) == want, raw


def test_urls_in_goal_summary_open_in_new_tab_on_every_page(tmp_path):
    """「做什么」里常带文档链接，原样当文字显示点不开。
    「做什么 / 做了什么 / 为什么放弃」里的网址都能点、新标签页打开；详情页、版本页、练手看板同一套。"""
    app, c = _client(tmp_path)
    _milestone(app, WEB, 9, "看板 v1.3.2")
    doc = "https://docs.example.com/d/a1b2c3"
    link = f'<a href="{doc}" target="_blank" rel="noopener">{doc}</a>'
    gid = _act(c, "create", title="APP 加广告", line="客户端", owner="linxia", version=f"{WEB}#9",
               note=f"业务验证通过算完。 业务说明（看「林夏」那一节）：{doc}")["goal_id"]
    assert f"业务说明（看「林夏」那一节）：{link}</span>" in c.get(f"/board/goal/{gid}").text
    _act(c, "complete", goal_id=gid, done_what=f"一期广告接全\n复盘见 {doc}。")
    assert f"复盘见 {link}。</span>" in c.get(f"/board/goal/{gid}").text
    assert f"复盘见 {link}。</div>" in c.get(f"/board/version?repo={WEB}&number=9").text
    gone = _act(c, "create", title="旧方案", line="客户端", owner="linxia")["goal_id"]
    _act(c, "abandon", goal_id=gone, reason=f"换成 {doc}")
    assert f"换成 {link}</span>" in c.get(f"/board/goal/{gone}").text
    assert c.post("/board/practice/reset", follow_redirects=False).status_code == 303
    assert f"业务说明（看「林夏」那一节）：{link}</span>" in c.get(f"/board/practice/goal/{gid}").text
    assert f"复盘见 {link}。</div>" in c.get(f"/board/practice/version?repo={WEB}&number=9").text


def test_tops_in_one_line_sort_by_number_not_due(tmp_path):
    """同一条线里顶层目标按编号排，不再按计划完成日：先立的没定日子、后立的日子最早，
    也是先立的在上；按数字比，第 10 个在第 9 个下面（防按字符串排）。"""
    _app, c = _client(tmp_path)
    ids = [_act(c, "create", title=f"顶层{i}号", line="增长", owner="linxia",
                occurred_at=f"2026-10-01T08:{i:02d}:00-07:00",
                **({} if i == 1 else {"due": f"2026-11-{30 - i:02d}"}))["goal_id"] for i in range(1, 11)]
    assert ids == sorted(ids)
    band = _band(c.get("/board").text, "增长")
    pos = [band.index(f">顶层{i}号</a>") for i in range(1, 11)]
    assert pos == sorted(pos)


def test_timeline_row_shows_birth_number_after_gnum(tmp_path):
    """时间线行上编号后面跟小字出生号「G1 · L24」，悬浮提示也带；团队看板直接立的没有出生号就不显示。"""
    _app, c = _client(tmp_path)
    a = _act(c, "create", title="个人看板推上来的", line="增长", owner="linxia", source="L24")["goal_id"]
    b = _act(c, "create", title="团队看板直接立的", line="增长", owner="zhouxing")["goal_id"]
    band = _band(c.get("/board").text, "增长")
    assert f'<span class="bd-gid">G{a}<span class="bd-src"' in band and f"> · L24</span></span>" in band
    assert f'title="G{a} · L24 个人看板推上来的 · ' in band
    assert f'<span class="bd-gid">G{b}</span>' in band and f'title="G{b} 团队看板直接立的 · ' in band
    assert band.count("bd-src") == 1
