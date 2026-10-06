from tests.conftest import client_as as _client


def test_owner_creates_via_api_and_goal_page_is_brief(tmp_path):
    _app, c = _client(tmp_path)
    api = c.post("/api/board/act", json={"action": "create", "params": {
        "title": "工程进度看板", "line": "管理与协作", "owner": "linxia", "due": "2026-10-02"}})
    assert api.status_code == 200 and api.json()["ok"]
    page = c.get("/board")
    assert page.status_code == 200 and "工程进度看板" in page.text and "待立项" not in page.text
    assert '<html lang="zh-CN">' in page.text
    goal = c.get("/board/goal/1").text
    assert "没分环节" in goal and "手动修改（备用" in goal and "拆出子目标" not in goal
    r = c.post("/board/act", data={"action": "start_stage", "goal_id": "1", "stage": "产品", "next": "/board/goal/1"},
               follow_redirects=False)
    assert r.status_code == 303 and "ok=" in r.headers["location"]
    bad = c.post("/board/act", data={"action": "change_due", "goal_id": "1", "due": "2026-13-40",
                                     "reason": "x", "next": "/board/goal/1"}, follow_redirects=False)
    assert "err=" in bad.headers["location"]


def test_root_redirects_to_board_and_old_pages_are_gone(tmp_path):
    """站上只有看板：首页直接到看板，别的路径 404。"""
    _app, c = _client(tmp_path)
    r = c.get("/", follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"] == "/board"
    for path in ("/upload", "/captions", "/plans", "/ops/intel", "/reports/", "/ops/shots", "/changes", "/templates"):
        assert c.get(path).status_code == 404, path
    page = c.get("/board").text
    assert "练手看板" in page and "<title>团队看板</title>" in page


def test_index_lists_each_persons_queue(tmp_path):
    _app, c = _client(tmp_path)
    c.post("/api/board/act", json={"action": "create", "params": {"title": "看板", "line": "管理与协作",
                                                                  "owner": "zhouxing", "due": "2026-10-02"}})
    page = c.get("/board").text
    assert "现在在做什么" in page and "手上的事" not in page and "管理与协作" in page and "P1" not in page
    r = c.get("/board?zoom=hour")                    # 没有的缩放：提示后用默认，不 500
    assert r.status_code == 200 and "没有这个缩放" in r.text


def test_actions_reference_and_notes_box(tmp_path):
    _app, c = _client(tmp_path)
    spec = c.get("/api/board/actions").json()
    assert spec["actions"]["add_note"]["required"] == ["text"] and "管理与协作" in spec["values"]["line"]
    c.post("/api/board/act", json={"action": "add_note", "params": {"text": "今天开始联调"}})
    page = c.get("/board").text
    assert "口述录入" in page and "今天开始联调" in page and "待录入" in page


def test_fold_happens_in_the_browser_without_reload(tmp_path):
    """点折叠整页闪一下 → 折叠改在浏览器里藏行，不再走服务端跳转。"""
    _app, c = _client(tmp_path)
    top = c.post("/api/board/act", json={"action": "create", "params": {
        "title": "新协作模式落地", "line": "管理与协作", "owner": "linxia"}}).json()["goal_id"]
    c.post("/api/board/act", json={"action": "create", "params": {
        "title": "团队进度看板", "owner": "linxia", "parent_id": top}})
    page = c.get("/board").text
    assert 'data-key="L:管理与协作"' in page and f'data-key="G:{top}"' in page
    assert f'data-anc="L:管理与协作 G:{top}"' in page          # 子目标带着能折叠它的开关
    assert "localStorage" in page and "/board/fold" not in page
    assert c.get("/board/fold?key=G:1", follow_redirects=False).status_code == 404


def test_one_strip_covers_everything_and_zoom_only_sets_screen_width():
    """时间线是一整条、左右拖；缩放只决定一屏看多长（最小一周、最大一季度）。"""
    from datetime import date

    from team_board.board.view import board_range, default_left, jump_options
    thu = date(2026, 10, 1)
    assert [default_left(thu, z) for z in ("week", "2week", "month", "quarter")] == [
        date(2026, 9, 28), date(2026, 9, 21), date(2026, 9, 14), date(2026, 7, 13)]
    lo, hi = board_range(thu, [date(2026, 5, 6)], [date(2026, 10, 20)])
    assert lo == date(2026, 5, 4) and hi == date(2026, 11, 8)                  # 盖住所有内容，周一到周日
    lo, hi = board_range(thu, [], [])
    assert lo == date(2026, 7, 13) and (hi - lo).days + 1 >= 91                # 至少够一季度看满一屏
    # 跳转顺序：现在这段在最上，往下越早；将来的放最后
    opts = jump_options(date(2026, 7, 13), date(2026, 10, 18), thu)
    assert [x for x, _ in opts["week"][:3]] == ["09-28 那周（本周）", "09-21 那周", "09-14 那周"]
    assert opts["week"][-2:] == [("10-05 那周", date(2026, 10, 5)), ("10-12 那周", date(2026, 10, 12))]
    assert opts["2week"] == opts["week"]
    assert [x for x, _ in opts["month"]] == ["2026 年 10 月（本月）", "2026 年 9 月", "2026 年 8 月", "2026 年 7 月"]
    assert [x for x, _ in opts["day"][:2]] == ["10-01 周四（今天）", "09-30 周三"]
    assert [x for x, _ in opts["quarter"]] == ["2026 年第 4 季度（本季度）", "2026 年第 3 季度"]


def test_goal_finished_long_ago_still_shows_at_every_zoom(tmp_path):
    """林夏截图：两周档里，早已结束的子目标不见了，只有一季度档才全——内容在哪一档都要是全的。"""
    _app, c = _client(tmp_path)
    gid = c.post("/api/board/act", json={"action": "create", "params": {
        "title": "八月就做完的事", "line": "客户端", "owner": "linxia",
        "occurred_at": "2026-08-01T10:00:00-07:00"}}).json()["goal_id"]
    c.post("/api/board/act", json={"action": "complete", "params": {
        "goal_id": gid, "occurred_at": "2026-08-05T10:00:00-07:00"}})
    for z in ("week", "2week", "month", "quarter"):
        page = c.get(f"/board?zoom={z}").text
        assert "八月就做完的事" in page and "开始 08-01" in page, z


def test_sample_board_is_a_separate_page_with_the_same_lines(tmp_path):
    """示例要和真实看板一模一样地展示——同一套页面、同样的线，放在独立页 /board/sample，
    真实目标照常显示（看板自己这个任务也按实际进度出现在示例里）、示例标「示例」；真实看板上看不到示例。"""
    _app, c = _client(tmp_path)
    c.post("/api/board/act", json={"action": "create", "params": {
        "title": "真的看板任务", "line": "管理与协作", "owner": "linxia"}})
    top = c.post("/api/board/act", json={"action": "create", "params": {
        "title": "订阅系统 1.0（按新方式）", "line": "增长", "owner": "zhouxing", "due": "2026-09-20",
        "sample": "1"}}).json()["goal_id"]
    child = c.post("/api/board/act", json={"action": "create", "params": {
        "title": "B 执行层", "owner": "zhouxing", "parent_id": top}}).json()["goal_id"]
    real = c.get("/board?zoom=week").text
    assert "B 执行层" not in real and "示例·" not in real and "看示例看板" in real and "zoom-week" in real
    sample = c.get("/board/sample?zoom=week").text
    assert "示例看板" in sample and 'data-key="L:增长"' in sample and "B 执行层" in sample
    assert "真的看板任务" in sample                                       # 真实目标也在示例看板上
    assert "示例·订阅系统 1.0（按新方式）：已超出计划" in sample          # 示例看板的卡点里示例标「示例·」
    assert "B 执行层" not in sample.split('id="bd-doing"')[1].split("</section>")[0] and "口述录入" not in sample   # 示例不算谁手上的事、也不进各线正在做
    assert 'class="bd-sampletag">示例' in sample
    assert c.get(f"/board/goal/{child}").text.count("示例（假设数据）") == 1
    real_id = c.post("/api/board/act", json={"action": "create", "params": {
        "title": "真目标", "line": "增长", "owner": "linxia"}}).json()["goal_id"]
    mixed = c.post("/api/board/act", json={"action": "edit_goal", "params": {"goal_id": real_id, "parent_id": str(top)}})
    assert mixed.status_code == 409
    bad = c.post("/api/board/act", json={"action": "create", "params": {
        "title": "x", "owner": "linxia", "parent_id": real, "sample": "1"}})
    assert bad.status_code == 400


def test_state_api_lists_notes_with_author_and_long_term_shows_on_pages(tmp_path):
    """AI 录口述前要从 /api/board/state 读到每条口述是谁写的、录过没有；
    长期负责的事在时间线和详情页显示「长期」，不显示「计划未定」。"""
    _app, c = _client(tmp_path)
    gid = c.post("/api/board/act", json={"action": "create", "params": {
        "title": "产品崩溃率", "line": "客户端", "owner": "zhouxing", "long_term": "1"}}).json()["goal_id"]
    c.post("/api/board/act", json={"action": "add_note", "params": {"text": "本周先看 3.8 的闪退", "goal_id": gid}})
    state = c.get("/api/board/state").json()
    assert state["goals"][0]["long_term"] is True
    note, = state["notes"]
    assert note["who"] == "林夏" and note["done"] is False and note["goal_id"] == gid \
        and note["goal_title"] == "产品崩溃率" and note["text"] == "本周先看 3.8 的闪退"
    index = c.get("/board").text
    assert "长期" in index and "计划未定" not in index
    goal = c.get(f"/board/goal/{gid}").text
    assert "长期负责" in goal and "计划未定" not in goal


def test_cross_line_family_shows_in_own_line_with_shared_tint_and_g_numbers(tmp_path):
    """一个业务目标拆到别的线的那块留在自己的线上，写「属于 G… 」，整家共用一个淡底色；
    目标编号全站写成 G17；线标题带序号；人名是颜色圆点加名字。"""
    _app, c = _client(tmp_path)
    top = c.post("/api/board/act", json={"action": "create", "params": {
        "title": "APP 加广告", "line": "客户端", "owner": "suhe", "due": "2026-10-10"}}).json()["goal_id"]
    sdk = c.post("/api/board/act", json={"action": "create", "params": {
        "title": "广告 SDK 接入", "owner": "zhouxing", "parent_id": top}}).json()["goal_id"]
    cfg = c.post("/api/board/act", json={"action": "create", "params": {
        "title": "后台广告配置界面", "owner": "suhe", "parent_id": top, "line": "运营"}}).json()["goal_id"]
    page = c.get("/board").text
    client_band = page.split('data-key="L:客户端"')[1].split("<section")[0]
    ops_band = page.split('data-key="L:运营"')[1].split("<section")[0]
    assert "后台广告配置界面" in ops_band and "后台广告配置界面" not in client_band
    assert f"属于 G{top} APP 加广告" in ops_band and "另 1 块在运营" in client_band
    assert page.count(f'data-fam="G{top}"') == 3 and "bd-fam0" in page       # 一家三块同一个底色
    assert f'<span class="bd-gid">G{top}.1</span>' in client_band and "（周行）" not in page
    assert f'<span class="bd-gid">G{top}.2</span>' in ops_band and sdk
    assert 'var(--p-zhouxing)' in client_band and '<span class="bd-lnum">①</span>客户端' in page
    goal = c.get(f"/board/goal/{cfg}").text
    assert f"G{top} APP 加广告" in goal and "（客户端）" in goal
    assert "bd-fam-note" in page and "里面还有同一家的" in page          # 收起来的那一行会提示里面还有同一家的块


def test_sample_page_renders_dependency_conflict_blocker(tmp_path):
    """实测：示例页里一有「依赖冲突」卡点就 500（卡点文案引用了删掉的函数）。"""
    _app, c = _client(tmp_path)
    a = c.post("/api/board/act", json={"action": "create", "params": {
        "title": "A", "line": "客户端", "owner": "linxia", "due": "2026-10-05", "sample": "1"}}).json()["goal_id"]
    b = c.post("/api/board/act", json={"action": "create", "params": {
        "title": "B", "line": "客户端", "owner": "linxia", "due": "2026-10-20", "sample": "1"}}).json()["goal_id"]
    r = c.post("/api/board/act", json={"action": "declare_dependency", "params": {
        "goal_id": a, "on_goal": b, "at_stage": "开发"}})
    assert r.status_code == 200, r.text
    page = c.get("/board/sample")
    assert page.status_code == 200 and "依赖冲突" in page.text


def test_goal_numbers_show_hierarchy_and_never_move(tmp_path):
    """编号要看得出从属——G17 的块是 G17.1、G17.2，再往下 G17.1.1；号发出去就不变：
    撤掉一块不会让后面的号前移，挪到别的上层下面拿新号。"""
    _app, c = _client(tmp_path)
    def mk(**params):
        return c.post("/api/board/act", json={"action": "create", "params": params}).json()["goal_id"]
    top = mk(title="母题", line="客户端", owner="linxia")
    a = mk(title="甲", owner="linxia", parent_id=top)
    b = mk(title="乙", owner="linxia", parent_id=top)
    aa = mk(title="甲一", owner="linxia", parent_id=a)
    nums = {g["id"]: g["gnum"] for g in c.get("/api/board/state").json()["goals"]}
    assert nums == {top: f"G{top}", a: f"G{top}.1", b: f"G{top}.2", aa: f"G{top}.1.1"}
    first_b = c.get(f"/board/goal/{b}").text.split("name=\"event_id\" value=\"")[-1].split('"')[0]   # 留痕倒序，最后一个是建目标那条
    assert c.post("/api/board/act", json={"action": "void", "params": {"event_id": int(first_b), "reason": "建错了"}}).json()["ok"]
    cc = mk(title="丙", owner="linxia", parent_id=top)
    nums = {g["id"]: g["gnum"] for g in c.get("/api/board/state").json()["goals"]}
    assert b not in nums and nums[cc] == f"G{top}.3"                      # 乙撤掉了，丙还是第 3 块
    c.post("/api/board/act", json={"action": "edit_goal", "params": {"goal_id": aa, "parent_id": str(top)}})
    nums = {g["id"]: g["gnum"] for g in c.get("/api/board/state").json()["goals"]}
    assert nums[aa] == f"G{top}.4"
    state = c.get("/api/board/state").json()
    c.post("/api/board/act", json={"action": "add_note", "params": {"text": "甲一今天开始", "goal_id": aa}})
    note, = c.get("/api/board/state").json()["notes"]
    assert note["goal_num"] == f"G{top}.4"
    page = c.get(f"/board/goal/{aa}").text
    assert f"改为从 G{top} 拆出" in page and f"G{top}.4</span> 甲一" in page


def test_person_filter_keeps_only_that_persons_things(tmp_path):
    """按人筛选：只留他的事（上层只作路径、变淡），没他事的线写明，卡点和手上的事也跟着筛。"""
    _app, c = _client(tmp_path)
    c.post("/api/board/act", json={"action": "create", "params": {
        "title": "新协作模式落地", "line": "管理与协作", "owner": "linxia"}})
    c.post("/api/board/act", json={"action": "create", "params": {
        "title": "上线部署", "parent_id": 1, "owner": "zhouxing", "due": "2099-10-02"}})   # 远期：写近期的日子，过了那天就算延期，这条会变红
    c.post("/api/board/act", json={"action": "create", "params": {
        "title": "情报库接入", "line": "增长", "owner": "linxia", "due": "2020-01-01"}})
    page = c.get("/board?person=zhouxing").text
    assert " bd-match\"" in page and "上线部署" in page and " bd-path\"" in page
    assert "情报库接入" not in page and "周行在这条线上没有事" in page
    assert "已超出计划" not in page                   # 林夏目标的延期卡点不显示
    assert "正在只看 周行的事" in page
    doing = page.split('id="bd-doing"')[1].split("</section>")[0]
    assert "上线部署" in doing and "新协作模式落地" not in doing      # 各线正在做：只列他的、不列纯拆给下层的上层
    assert 'data-people="zhouxing:周行"' in page
    everyone = c.get("/board").text
    assert " bd-match\"" not in everyone and "已超出计划" in everyone


def test_active_only_keeps_child_whose_parent_is_hidden(tmp_path):
    """母题放弃后「只看进行中」，仍在做的同线子块不能从时间线消失。"""
    _app, c = _client(tmp_path)
    c.post("/api/board/act", json={"action": "create", "params": {"title": "母题", "line": "客户端", "owner": "linxia"}})
    c.post("/api/board/act", json={"action": "create", "params": {"title": "还在做的子块", "parent_id": 1, "owner": "zhouxing"}})
    c.post("/api/board/act", json={"action": "start_stage", "params": {"goal_id": 2, "stage": "开发"}})
    c.post("/api/board/act", json={"action": "abandon", "params": {"goal_id": 1, "reason": "不做了"}})
    page = c.get("/board?active=1").text
    tl = page.split('id="bd-tl"')[1]
    assert "还在做的子块" in tl and "母题" not in tl


def test_resolve_api_and_goal_page_show_source(tmp_path):
    """按任意号查目标：接口返回显示号、永久号、来源号和关联的单；详情页写「来源 L16」。"""
    _app, c = _client(tmp_path)
    for params in ({"title": "新协作模式落地", "line": "管理与协作", "owner": "linxia"},
                   {"title": "AI 记账", "owner": "linxia", "parent_id": 1, "source": "L16"}):
        assert c.post("/api/board/act", json={"action": "create", "params": params}).json()["ok"]
    assert c.post("/api/board/act", json={"action": "link_issue", "params": {
        "goal_id": 2, "repo": "acme/web", "number": 300, "kind": "link"}}).json()["ok"]
    for num in ("L16", "G2", "G1.1"):
        r = c.get("/api/board/resolve", params={"num": num})
        assert r.status_code == 200, num
        body = r.json()
        assert (body["id"], body["gnum"], body["permanent"], body["source"]) == (2, "G1.1", "G2", "L16")
        assert body["issues"] == [{"repo": "acme/web", "number": 300, "kind": "link",
                                   "title": "", "url": "", "state": ""}]
    miss = c.get("/api/board/resolve", params={"num": "L99"})
    assert miss.status_code == 404 and "L99" in miss.json()["error"]
    state = c.get("/api/board/state").json()["goals"]
    assert [(g["permanent"], g["source"]) for g in state] == [("G1", ""), ("G2", "L16")]
    assert "来源 L16" in c.get("/board/goal/2").text and "来源" not in c.get("/board/goal/1").text.split("bd-head")[1].split("</div>")[0]
    assert c.get("/api/board/practice/resolve", params={"num": "L16"}).json()["practice"] is True   # 练手库是正式库的副本
    # 早先推上来没带来源号的，林夏补上；详情页的记录里写「补上来源号」，页面不能因为认不出这种修改而打不开
    assert c.post("/api/board/act", json={"action": "edit_goal", "params": {"goal_id": 1, "source": "L3"}}).json()["ok"]
    page = c.get("/board/goal/1")
    assert page.status_code == 200 and "来源 L3" in page.text and "补上来源号 L3" in page.text
    assert "立项：AI 记账（管理与协作），来源 L16" in c.get("/board/goal/2").text
