"""Demo data and reset.

`seed_demo` fills an empty main database with a fictional board so a fresh install looks like one in daily
use. Everything is dated relative to the day it is seeded (in the main time zone): the last few days carry
10–25 entries each, spread over the working hours.

The fiction: a small startup building the pet-care app "Pawprint". The board belongs to the lead
(configure `person` as Alex / letter A — or 林夏 / L for the Chinese set). Ben does the backend, Chloe design and
testing; their goals live on the team board and, as with a real pull, only the lead's own goals (and their
parents) are on this board. Lines and stages are taken from the config by position, the text from `lang`.

`reset_main` backs the main database up and starts an empty one (birth numbers keep counting).
"""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

from app import settings
from app.actions import ActionError, apply_action
from app.i18n import t
from app.model import local_day
from app.store import birth_floor, db_path, get_meta, open_db, set_meta
from app.settings import data_dir

TABLES = ("goals", "entries", "todos", "notes")


def is_empty(conn: sqlite3.Connection) -> bool:
    return not any(conn.execute(f"SELECT COUNT(*) FROM {tb}").fetchone()[0] for tb in TABLES)


def seed_demo(conn: sqlite3.Connection, lang: str, now: datetime) -> dict:
    """Empty database ← the demo board. Refuses a database that already holds anything."""
    if lang not in settings.LANGS:
        raise ValueError(t("seed.bad_lang"))
    if not is_empty(conn):
        raise ValueError(t("seed.not_empty"))
    zh = lang == "zh"
    x = lambda a, b: a if zh else b  # noqa: E731 — pick the text of the seeded language
    tz = settings.tz()
    today = local_day(now)
    team = settings.team_line_names() or settings.line_names()
    line = lambda i: team[min(i, len(team) - 1)]  # noqa: E731 — 0 product, 1 growth, 2 operations, 3 team
    personal = next((ln["name"] for ln in settings.lines() if ln["personal"]), settings.line_names()[-1])
    names = settings.stage_names()
    BIZ, PROD, UI, DEV, TEST = (names[min(i, len(names) - 1)] for i in range(5))

    def at(day: int, hm: str, base: date | None = None) -> datetime:
        h, m = (int(v) for v in hm.split(":"))
        d = (base or today) + timedelta(days=day)
        return datetime(d.year, d.month, d.day, h, m, tzinfo=tz)

    def day(offset: int) -> str:
        return str(today + timedelta(days=offset))

    # The monthly point task: the 1st of every month at 10:00. Last month's was done; this month's is still open.
    prev_first = (today.replace(day=1) - timedelta(days=1)).replace(day=1)

    events: list[tuple[datetime, str, str | None, dict]] = []   # (when, action, goal key, params)
    gnums: dict[str, str] = {}                                    # goal key → number, filled as goals are created
    team_ids = {"g1": 1, "g2": 5, "g3": 6, "g5": 10, "g6": 11, "g62": 13, "g63": 14}
    sync_of = {"book": "skip", "pay": "skip", "rate": "pending"}  # everything else on a team line is already pushed

    def ev(when: datetime, action: str, key: str | None = None, **params) -> None:
        events.append((when, action, key, params))

    def create(when, key, title, ln, **params):
        ev(when, "goal_create", key, title=title, line=ln, **params)

    def stage(key, st, start, end=None):
        ev(start, "stage_start", key, stage=st)
        if end is not None:
            ev(end, "stage_end", key, stage=st)

    def log(when, key, kind, text, task, tool="claude", st=None, **params):
        ev(when, "log", key, kind=kind, text=text, task=task, tool=tool, **({"stage": st} if st else {}), **params)

    # conversations of the day (the `task` of an entry) — several run in parallel, some in Claude Code, some in Codex
    T_ONB, T_QA = x("引导改版开发", "Onboarding build"), x("引导页回归测试", "Onboarding regression")
    T_REM, T_REMQA = x("提醒页面", "Reminder screens"), x("提醒页面测试", "Reminder QA")
    T_MEM, T_WAY = x("会员订阅跟进", "Membership follow-up"), x("协作方式落地", "New way of working")
    T_RATE, T_BOOK, T_SCHED = x("评分引导", "Rating prompt"), x("手册整理", "Playbook upkeep"), x("提醒调度", "Reminder scheduling")
    T_VET = x("医院落地页", "Clinic landing page")
    book_v = lambda v: x(f"手册 {v}", f"Playbook {v}")  # noqa: E731

    # ---------- long-running row, point task, personal errand (birth numbers 1–3) ----------
    create(at(-12, "09:00", prev_first), "book", x("个人手册持续沉淀", "Personal playbook upkeep"), line(3), long_term=True,
           next_step=x("有新经验就写进去", "Add a rule whenever something is learned the hard way"))
    log(at(-12, "09:30", prev_first), "book", "digest", version=book_v("1.0.0"), task=T_BOOK,
        text=x("手册 1.0.0：先有三条——对话一开始先归类、出了结果记一条、收尾写下一步",
               "Playbook 1.0.0: the first three rules — file every conversation up front, log each visible result, end with the next step"))
    create(at(-5, "10:00", prev_first), "pay", x("每月 1 号给外包结款", "Pay contractors on the 1st"), line(2),
           point_at=f"{prev_first} 10:00", repeat="monthly", task=x("月度结款", "Monthly payments"), tool="claude")
    ev(at(0, "10:40", prev_first), "point_done", "pay", occurrence=f"{prev_first} 10:00", task=x("月度结款", "Monthly payments"), tool="claude")
    create(at(-12, "20:00"), "passport", x("护照续签", "Renew passport"), personal, due=day(20),
           next_step=x("预约递交材料的时间", "Book a slot to hand in the papers"))
    log(at(-9, "17:30"), "book", "digest", version=book_v("1.1.0"), task=T_BOOK,
        text=x("手册 1.1.0：第一次进新环节先把上一环节的产出列出来，等我点头",
               "Playbook 1.1.0: before entering a stage for the first time, list what the previous one produced and wait for my nod"))

    # ---------- G3 Vet-clinic partner landing page: finished last week ----------
    create(at(-14, "09:00"), "g3", x("宠物医院合作落地页", "Vet-clinic partner landing page"), line(1), gnum="G3", due=day(-5),
           what=x("合作医院有自己的落地页，扫码就能预约；第一家医院上线并带来注册算完。",
                  "Each partner clinic gets its own landing page with booking by QR code; done when the first clinic is live and brings sign-ups."))
    stage("g3", BIZ, at(-14, "09:10"), at(-13, "12:00"))
    stage("g3", PROD, at(-13, "13:00"), at(-11, "17:00"))
    stage("g3", UI, at(-12, "10:00"), at(-10, "15:00"))
    stage("g3", DEV, at(-10, "09:00"), at(-7, "18:00"))
    stage("g3", TEST, at(-7, "10:00"), at(-5, "16:00"))
    log(at(-13, "11:40"), "g3", "result", x("和第一家医院谈定：他们出场地海报，我们出落地页和首次体检优惠",
                                          "Agreed with the first clinic: they put up the posters, we provide the page and a first-checkup offer"), T_VET, st=BIZ)
    log(at(-10, "14:30"), "g3", "result", x("页面设计定稿，医院看过没有意见", "Page design signed off; the clinic had no changes"), T_VET, st=UI)
    log(at(-7, "17:20"), "g3", "result", x("落地页上线到测试环境，扫码能走到预约", "Page is up on staging; scanning the code leads all the way to a booking"), T_VET, st=DEV)
    log(at(-6, "15:00"), "g3", "result", x("测出优惠券重复领取，已修", "Testing found the coupon could be claimed twice; fixed"), T_VET, "codex", st=TEST)
    ev(at(-5, "16:30"), "complete", "g3", task=T_VET, tool="claude",
       done_what=x("合作医院有了专属落地页：\n· 扫码就能看到医院介绍和预约入口\n· 新用户注册后自动领一张首次体检优惠券\n· 后台能看到每家医院带来了多少注册",
                   "Partner clinics now have their own landing page:\n· Scan the code to see the clinic and book a visit\n· New users get a first-checkup coupon automatically\n· The admin shows how many sign-ups each clinic brought"))

    # ---------- G1 Launch paid membership: the lead starts it and does the business stage; three blocks go to Ben and Chloe ----------
    create(at(-12, "10:00"), "g1", x("会员订阅上线", "Launch paid membership"), line(0), gnum="G1", due=day(9),
           what=x("用户能在 App 里订阅月付或年付会员并自动续费；真实付款走通、上线三天没有支付类故障算完。",
                  "Users can subscribe monthly or yearly in the app with auto-renewal; done when a real payment goes through and three days pass without a payment incident."),
           next_step=x("周四和周行联调支付，之后验收会员页面", "Test payments end to end with Ben on Thursday, then review the membership screens"))
    stage("g1", BIZ, at(-12, "10:05"), at(-11, "16:00"))
    log(at(-11, "16:10"), "g1", "result", x("拆成三块：支付与订阅后端给周行，会员页面给苏禾，后台价格配置给苏禾",
                                                    "Split into three blocks: payments & subscription backend to Ben, membership screens to Chloe, admin pricing to Chloe"), T_MEM)

    # ---------- G5 Roll out the new way of working: no stages ----------
    create(at(-10, "11:00"), "g5", x("新协作方式落地", "Roll out the new way of working"), line(3), gnum="G5", due=day(14),
           what=x("三个人都用看板记进展、每周对一次；连续两周不靠口头同步算完。",
                  "All three of us log progress on the board and review it weekly; done after two weeks without status meetings."),
           next_step=x("下周一给团队演示看板怎么用", "Demo the board to the team next Monday"))
    log(at(-8, "16:00"), "g5", "result", x("和周行、苏禾聊定：每人对自己的块负责到底，卡住了在看板上标出来",
                                         "Agreed with Ben and Chloe: each owns their block end to end and flags blockers on the board"), T_WAY)

    # ---------- G2 New-user onboarding redesign: created here (4th birth number), pushed, done single-handed; running late ----------
    create(at(-9, "09:30"), "g2", x("新用户引导改版", "New-user onboarding redesign"), line(0), due=day(-1),
           what=x("新用户三步内添加好第一只宠物；注册到添加完成的比例从 41% 提到 60% 算完。",
                  "A new user adds their first pet within three steps; done when sign-up-to-first-pet rises from 41% to 60%."),
           next_step=x("看灰度数据，注册到添加完成的比例到 60% 就收口", "Watch the rollout numbers; close once sign-up-to-first-pet reaches 60%"),
           task=T_ONB, tool="claude")
    ev(at(-9, "18:00"), "goal_update", "g2", gnum="G2")   # pushed at that day's wrap-up: the display number becomes the team's
    stage("g2", BIZ, at(-9, "09:35"), at(-8, "12:00"))
    stage("g2", PROD, at(-8, "13:00"), at(-6, "17:00"))
    stage("g2", UI, at(-7, "10:00"), at(-5, "15:00"))
    stage("g2", DEV, at(-5, "09:00"), at(-3, "09:50"))
    stage("g2", TEST, at(-3, "10:00"), at(-3, "16:00"))
    stage("g2", DEV, at(-3, "16:10"), at(-2, "15:00"))
    stage("g2", TEST, at(-2, "15:10"), at(-1, "11:00"))
    stage("g2", PROD, at(-1, "11:10"), at(-1, "12:00"))
    stage("g2", DEV, at(-1, "13:00"), at(0, "09:05"))
    stage("g2", TEST, at(0, "09:10"))
    log(at(-8, "11:30"), "g2", "result", x("看了 20 个新用户的录屏：一半卡在「先注册还是先加宠物」", "Watched 20 new-user recordings: half got stuck on \"sign up first or add a pet first\""), T_ONB, st=BIZ)
    log(at(-6, "16:30"), "g2", "result", x("方案定稿：三步——注册、添加宠物、开启提醒，每步只做一件事", "Spec final: three steps — sign up, add a pet, turn on reminders; one thing per step"), T_ONB, st=PROD)
    log(at(-5, "14:30"), "g2", "result", x("三步的页面设计定稿", "Design for the three steps signed off"), T_ONB, st=UI)
    log(at(-4, "17:00"), "g2", "result", x("注册和添加宠物两步做完", "Sign-up and add-a-pet steps built"), T_ONB, st=DEV)
    ev(at(-2, "18:00"), "goal_update", "g2", due=day(1), reason=x("弱网问题要多修一轮", "one more round for the slow-network bug"))

    # ---------- G6 Smart feeding reminders 1.0: G6.1 is Ben's (not on this board); G6.2 and G6.3 are the lead's ----------
    create(at(-8, "10:00"), "g6", x("智能喂养提醒 1.0", "Smart feeding reminders 1.0"), line(0), gnum="G6", due=day(12),
           what=x("主人给每只宠物设好喂养时间，到点手机收到提醒；连续一周提醒不漏不重算完。",
                  "Owners set feeding times per pet and get a phone reminder on time; done after a week with no missed or duplicate reminders."),
           next_step=x("三块都做完后整体走一遍再验收", "When all three blocks are done, walk the whole flow before sign-off"))
    stage("g6", BIZ, at(-8, "10:05"), at(-7, "11:00"))
    log(at(-7, "11:05"), "g6", "result", x("拆成三块：推送服务与接口给周行整包；提醒页面、调度逻辑我自己做",
                                         "Split into three blocks: push service & API to Ben as a whole; reminder screens and scheduling are mine"), T_REM)
    create(at(-7, "11:10"), "g62", x("App 提醒页面", "Reminder screens"), line(0), gnum="G6.2", parent_gnum="G6", due=day(6),
           next_step=x("等推送接口出来联调提醒页面", "Hook the screens up to the push API once it lands"))
    stage("g62", PROD, at(-7, "11:15"), at(-5, "12:00"))
    stage("g62", UI, at(-6, "10:00"), at(-4, "16:00"))
    stage("g62", DEV, at(-4, "09:30"), at(-2, "12:00"))
    stage("g62", TEST, at(-2, "13:00"), at(-1, "10:00"))
    stage("g62", DEV, at(-1, "10:10"), at(0, "13:50"))
    stage("g62", TEST, at(0, "14:00"))
    log(at(-5, "11:40"), "g62", "result", x("方案定了：提醒列表、新建提醒、提醒详情三个页面", "Spec set: three screens — reminder list, new reminder, reminder detail"), T_REM, st=PROD)
    log(at(-4, "15:30"), "g62", "result", x("三个页面的设计定稿", "Design for the three screens signed off"), T_REM, st=UI)
    create(at(-7, "11:20"), "g63", x("提醒调度逻辑", "Reminder scheduling"), line(0), gnum="G6.3", parent_gnum="G6", due=day(8),
           next_step=x("推送接口给到后开工开发", "Start the build as soon as the push API is delivered"))
    stage("g63", PROD, at(-6, "14:00"), at(-5, "17:00"))
    log(at(-5, "16:50"), "g63", "result", x("规则定了：同一只宠物同一时刻只发一条；主人关了通知就改发站内信",
                                          "Rules set: one reminder per pet per moment; if notifications are off, fall back to an in-app message"), T_SCHED, "codex", st=PROD)
    ev(at(-5, "17:05"), "goal_update", "g63", blocker=t("team.paused", lang=lang, kind=x("等依赖", "waiting on a dependency")))
    log(at(-5, "17:06"), "g63", "note", x("开发要等 G6.1 的推送接口，先停在这", "The build waits on G6.1's push API; parked here for now"), T_SCHED, "codex")

    # ---------- three days ago ----------
    d = -3
    log(at(d, "09:02"), "g2", "start", x("开工：把「添加宠物」这一步的表单收尾，然后进测试", "Starting: finish the add-a-pet form, then move to testing"), T_ONB, st=DEV)
    log(at(d, "09:20"), "g62", "start", x("开工：提醒列表页接上假数据，先把交互跑通", "Starting: wire the reminder list to mock data and get the interaction working"), T_REM, st=DEV)
    log(at(d, "09:45"), "g2", "result", x("三步引导在真机上跑通：注册 → 添加宠物 → 开启提醒", "All three steps run on a real phone: sign up → add a pet → turn on reminders"), T_ONB, st=DEV)
    log(at(d, "10:05"), "g2", "start", x("开工：第一轮测试，按 12 条用例过", "Starting: first test round, 12 cases"), T_QA, "codex", st=TEST)
    log(at(d, "10:40"), "g2", "result", x("第一轮测完 12 条，过 9 条", "Round one done: 9 of 12 pass"), T_QA, "codex", st=TEST)
    log(at(d, "11:10"), "g62", "result", x("提醒列表、新建提醒两个页面能点通了", "The reminder list and new-reminder screens click through"), T_REM, st=DEV)
    log(at(d, "11:20"), "g2", "note", x("没过的三条：宠物生日选今天会报错；头像上传后不刷新；返回键会丢已填内容",
                                       "The three failures: picking today as the pet's birthday errors out; the avatar does not refresh after upload; Back loses what was typed"), T_QA, "codex", st=TEST)
    log(at(d, "11:35"), "g5", "start", x("开工：把团队看板的四条线和五个环节各写一句说明", "Starting: one sentence each for the team board's four lines and five stages"), T_WAY)
    log(at(d, "12:10"), "g5", "result", x("线和环节的说明写完，发给周行、苏禾看", "Line and stage notes written and sent to Ben and Chloe"), T_WAY)
    log(at(d, "14:05"), "g1", "start", x("开工：看苏禾的会员页面初稿", "Starting: review Chloe's first draft of the membership screens"), T_MEM)
    log(at(d, "14:50"), "g1", "result", x("会员页面初稿看完，提了三处：价格对比不清楚、年付没标省多少、取消入口太深",
                                        "Reviewed the draft, three notes: plan comparison is unclear, yearly does not show the saving, Cancel is buried too deep"), T_MEM)
    log(at(d, "15:30"), "g2", "result", x("返回键丢内容当场修了；另外两条要回开发改", "Fixed the Back bug on the spot; the other two go back to dev"), T_QA, "codex", st=TEST)
    log(at(d, "16:15"), "g2", "start", x("开工：修生日报错和头像不刷新", "Starting: fix the birthday error and the stale avatar"), T_ONB, st=DEV)
    log(at(d, "16:40"), "g62", "result", x("「每天几点提醒」的时间选择做完，支持一天多次", "Time picker for \"remind me at\" done; several times a day supported"), T_REM, st=DEV)
    log(at(d, "17:20"), "g2", "result", x("生日报错修好，原因是时区换算少算了一天", "Birthday error fixed — a time-zone conversion was off by one day"), T_ONB, st=DEV)
    log(at(d, "17:40"), "g2", "wrap", x("今天：三步引导跑通并测了两轮；明天修头像刷新后再测一轮", "Today: three steps running, two test rounds done. Tomorrow: fix the avatar refresh, then another round"), T_ONB, st=DEV)
    log(at(d, "17:50"), "g62", "wrap", x("今天：两个页面和时间选择做完；明天接真实接口前先自测一遍", "Today: two screens and the time picker done. Tomorrow: self-test before wiring the real API"), T_REM, st=DEV)

    # ---------- two days ago ----------
    d = -2
    log(at(d, "08:50"), "book", "start", x("开工：把这两天测引导页的经验写进手册", "Starting: write the lessons from testing onboarding into the playbook"), T_BOOK)
    log(at(d, "09:20"), "book", "digest", version=book_v("1.2.0"), task=T_BOOK,
        text=x("手册 1.2.0：测出问题回开发不算回退，环节往返照实记", "Playbook 1.2.0: going back to dev after a failed test is not a step backwards — log the back-and-forth as it happens"))
    log(at(d, "09:30"), "g2", "start", x("开工：修头像上传后不刷新", "Starting: fix the avatar that does not refresh after upload"), T_ONB, st=DEV)
    log(at(d, "09:40"), "g62", "start", x("开工：自测提醒页面，把问题列出来", "Starting: self-test the reminder screens and list the issues"), T_REM, st=DEV)
    log(at(d, "10:15"), "g2", "result", x("头像不刷新修好：上传成功后直接用本地图，不再等服务器回图", "Avatar fixed: show the local image right after upload instead of waiting for the server"), T_ONB, st=DEV)
    log(at(d, "11:00"), "g62", "result", x("自测过了一遍，改掉 4 个小问题，可以进测试", "Self-test done, four small issues fixed; ready for testing"), T_REM, st=DEV)
    ev(at(d, "11:05"), "note_add", None, text=x("引导页第三步的提醒开关默认开，产品方案里是这么定的，记到 G2 上",
                                              "In onboarding step three the reminder switch should default to on — that is what the spec says. Put it on G2"))
    log(at(d, "11:06"), "g2", "result", x("第三步的提醒开关默认改成开（按口述 #1）", "Step three: reminder switch now defaults to on (dictation #1)"), T_ONB, st=DEV)
    ev(at(d, "11:08"), "note_resolve", None, note_id=1, summary=x("已记到 G2：提醒开关默认改成开", "Logged on G2: reminder switch defaults to on"))
    log(at(d, "11:30"), "g1", "result", x("苏禾按三处意见改完，会员页面第二稿通过", "Chloe addressed all three notes; second draft of the membership screens approved"), T_MEM)
    log(at(d, "13:05"), "g62", "start", x("开工：提醒页面第一轮测试，18 条用例", "Starting: first test round for the reminder screens, 18 cases"), T_REMQA, "codex", st=TEST)
    log(at(d, "13:10"), "g5", "start", x("开工：准备周一的看板演示", "Starting: prepare Monday's board demo"), T_WAY)
    log(at(d, "13:50"), "g5", "result", x("演示的例子选好了：拿会员订阅这件事讲怎么拆块", "Picked the demo example: how the membership launch was split into blocks"), T_WAY)
    ev(at(d, "13:55"), "todo_add", "g5", text=x("周一演示前把例子的截图备好", "Get the example screenshots ready before Monday's demo"))
    log(at(d, "14:30"), "g2", "note", x("周行提醒：新接口下周一才上，引导页先用旧接口", "Ben's heads-up: the new API ships next Monday; onboarding stays on the old one for now"), T_ONB, st=DEV)
    log(at(d, "15:20"), "g2", "start", x("开工：第三轮回归", "Starting: regression round three"), T_QA, "codex", st=TEST)
    log(at(d, "15:40"), "g62", "result", x("第一轮 18 条过 14 条；没过的都和「重复提醒」有关", "Round one: 14 of 18 pass; every failure is about duplicate reminders"), T_REMQA, "codex", st=TEST)
    log(at(d, "16:30"), "g2", "result", x("12 条全过；又加了 4 条弱网用例，过 3 条", "All 12 pass; added four slow-network cases, three pass"), T_QA, "codex", st=TEST)
    log(at(d, "17:10"), "g1", "note", x("和周行过了一遍续费失败怎么处理：先重试三次，再提醒用户换卡", "Walked through failed renewals with Ben: retry three times, then ask the user to update their card"), T_MEM)
    log(at(d, "17:45"), "g2", "wrap", x("今天：两处问题修完、回归通过；弱网下还有 1 条没过，明天看", "Today: both bugs fixed, regression green; one slow-network case still fails — tomorrow"), T_QA, "codex", st=TEST)
    log(at(d, "18:10"), "g62", "wrap", x("今天：自测后进了测试；重复提醒有 4 条没过，明天回开发改", "Today: self-tested and into testing; four duplicate-reminder cases fail — back to dev tomorrow"), T_REMQA, "codex", st=TEST)

    # ---------- yesterday ----------
    d = -1
    log(at(d, "09:00"), "g2", "start", x("开工：查弱网下添加宠物偶尔转圈不停", "Starting: chase the endless spinner when adding a pet on a slow network"), T_QA, "codex", st=TEST)
    log(at(d, "09:40"), "g2", "result", x("弱网问题复现了：请求超时后没有给重试按钮", "Reproduced: after a timeout there is no way to retry"), T_QA, "codex", st=TEST)
    log(at(d, "10:15"), "g62", "start", x("开工：改重复提醒——同一时间的两条要合并成一条", "Starting: fix duplicates — two reminders at the same time become one"), T_REM, st=DEV)
    create(at(d, "10:20"), "rate", x("应用商店评分引导", "App Store rating prompt"), line(1), due=day(7),
           what=x("在合适的时机请老用户去应用商店打分；上线两周、商店评分从 4.2 升到 4.5 算完。",
                  "Ask long-time users for an App Store rating at the right moment; done when the store rating rises from 4.2 to 4.5 two weeks after launch."),
           next_step=x("写产品方案", "Write the product spec"), task=T_RATE, tool="claude")
    stage("rate", BIZ, at(d, "10:25"), at(d, "16:40"))
    log(at(d, "10:30"), "rate", "start", x("开工：想清楚什么时候请用户打分、请哪些用户", "Starting: decide when to ask for a rating, and whom"), T_RATE, st=BIZ)
    log(at(d, "11:15"), "g2", "result", x("超时提示的文案定了：「网络有点慢，再试一次」，旁边加重试按钮", "Timeout copy settled: \"The network is slow — try again\", with a Retry button next to it"), T_ONB, st=PROD)
    log(at(d, "13:40"), "rate", "result", x("定了：只问用了满 30 天、最近一周记过 3 次照护的用户；一个月内报过问题的不问",
                                          "Decided: only users past 30 days who logged care three times in the last week; nobody who reported a problem in the past month"), T_RATE, st=BIZ)
    log(at(d, "14:30"), "g2", "result", x("超时重试做完，弱网下三步都能走通", "Retry on timeout done; all three steps work on a slow network"), T_ONB, st=DEV)
    log(at(d, "15:00"), "g62", "result", x("重复提醒合并做完，另外补了「今天不再提醒」", "Duplicate merging done, plus a new \"no more reminders today\""), T_REM, st=DEV)
    log(at(d, "15:10"), "g5", "result", x("看板演示稿过了一遍，压到 15 分钟", "Ran through the demo script and cut it to 15 minutes"), T_WAY)
    ev(at(d, "15:15"), "todo_done", None, todo_id=1)
    log(at(d, "15:40"), "g1", "result", x("周行说支付沙盒已通，周四可以联调", "Ben says the payment sandbox works; end-to-end test on Thursday"), T_MEM)
    ev(at(d, "15:45"), "todo_add", "g1", text=x("周四和周行联调支付沙盒", "Thursday: end-to-end payment test with Ben"))
    log(at(d, "16:20"), "book", "digest", version=book_v("1.2.1"), task=T_BOOK,
        text=x("手册 1.2.1：立项时计划完成日单独问一句，不默认空着", "Playbook 1.2.1: when creating a goal, ask for the planned finish date separately — never leave it blank by default"))
    log(at(d, "16:30"), "g63", "note", x("问了周行：推送接口预计后天给到，调度逻辑先不动", "Asked Ben: the push API should arrive the day after tomorrow; scheduling stays parked"), T_SCHED, "codex")
    log(at(d, "16:45"), "rate", "wrap", x("今天：业务想清楚了；下一步写产品方案", "Today: the business side is clear. Next: the product spec"), T_RATE)
    log(at(d, "17:30"), "g2", "wrap", x("今天：弱网问题定位并修完；明天全量回归，过了就可以灰度", "Today: slow-network bug found and fixed. Tomorrow: full regression, then a staged rollout"), T_ONB, st=DEV)
    log(at(d, "17:40"), "g62", "wrap", x("今天：重复提醒改完；明天再进测试", "Today: duplicates fixed. Tomorrow: back into testing"), T_REM, st=DEV)
    log(at(d, "18:30"), "passport", "note", x("证件照拍好了，电子版存在相册里", "Passport photo taken; the digital copy is in my photos"), x("个人事项", "Personal"))
    ev(at(d, "18:35"), "todo_add", "passport", text=x("预约护照续签的递交时间", "Book a slot to hand in the passport renewal"))
    ev(at(d, "19:00"), "note_add", None, text=x("评分引导加一条：刚给过差评反馈的用户别再弹，做方案时别漏了",
                                              "Rating prompt: never show it to someone who just sent negative feedback — do not forget that in the spec"))

    # ---------- today (only what has already happened by the time of seeding is written) ----------
    d = 0
    log(at(d, "08:45"), "g2", "start", x("开工：全量回归前先合并昨天的修复", "Starting: merge yesterday's fixes before the full regression"), T_ONB, st=DEV)
    log(at(d, "09:15"), "g2", "start", x("开工：全量回归，32 条", "Starting: full regression, 32 cases"), T_QA, "codex", st=TEST)
    log(at(d, "09:30"), "g62", "start", x("开工：把「今天不再提醒」接到列表页", "Starting: wire \"no more reminders today\" into the list screen"), T_REM, st=DEV)
    log(at(d, "09:50"), "g2", "result", x("跑了一半，16 条全过", "Halfway: 16 of 16 pass"), T_QA, "codex", st=TEST)
    log(at(d, "10:30"), "rate", "start", x("开工：写评分引导的产品方案", "Starting: write the product spec for the rating prompt"), T_RATE)
    log(at(d, "11:10"), "g2", "result", x("32 条全过", "All 32 pass"), T_QA, "codex", st=TEST)
    log(at(d, "11:40"), "g1", "note", x("苏禾问年付要不要送一个月，等周四联调后一起定", "Chloe asks whether yearly should include a free month; decide after Thursday's test"), T_MEM)
    log(at(d, "13:30"), "g5", "start", x("开工：把周一演示的反馈整理成待办", "Starting: turn Monday's demo feedback into to-dos"), T_WAY)
    log(at(d, "13:45"), "g62", "result", x("「今天不再提醒」接好了，可以再进测试", "\"No more reminders today\" wired in; ready for testing again"), T_REM, st=DEV)
    log(at(d, "14:05"), "g62", "start", x("开工：重复提醒回归", "Starting: regression on duplicate reminders"), T_REMQA, "codex", st=TEST)
    log(at(d, "14:10"), "g5", "result", x("三条反馈记下了：环节名要短、想看别人的块、手机上也要能看", "Three notes taken: shorter stage names, see other people's blocks, make it usable on a phone"), T_WAY)
    log(at(d, "15:00"), "rate", "result", x("方案初稿：记完一次照护后问一次，一年最多问三次，点「以后再说」90 天内不再问",
                                          "First draft: ask right after a care entry is logged, three times a year at most; \"Not now\" means no asking for 90 days"), T_RATE)
    log(at(d, "15:30"), "g62", "result", x("重复提醒 4 条全过", "All four duplicate-reminder cases pass"), T_REMQA, "codex", st=TEST)
    log(at(d, "16:00"), "g2", "note", x("已灰度 10% 新用户，观察一天注册到添加完成的比例", "Rolled out to 10% of new users; watching sign-up-to-first-pet for a day"), T_QA, "codex", st=TEST)
    log(at(d, "17:00"), "g2", "wrap", x("今天：全量回归通过、已灰度；明天看数据，达标就收口", "Today: full regression green, staged rollout started. Tomorrow: check the numbers and close if they hold"), T_QA, "codex", st=TEST)
    log(at(d, "17:10"), "g62", "wrap", x("今天：回归通过；等推送接口出来联调", "Today: regression green. Waiting for the push API to hook things up"), T_REMQA, "codex", st=TEST)

    # ---------- apply, oldest first; each event is written as if it had been logged at its own moment ----------
    n = skipped = 0
    for when, action, key, params in sorted(events, key=lambda e: e[0]):
        if when > now:
            continue
        if key is not None and action != "goal_create":
            if key not in gnums:
                continue
            params = dict(params, goal=gnums[key])
        if action in ("goal_create", "stage_start", "stage_end", "complete", "goal_update") and key is not None:
            params = dict(params, _sync=sync_of.get(key, "pushed"))
        try:
            r = apply_action(conn, action, params, when, internal=True)
        except ActionError:   # a config with fewer lines or stages than the story uses: drop the step, keep the rest
            skipped += 1
            continue
        if action == "goal_create":
            gnums[key] = r.gnum
        n += 1
    with conn:
        for key, team_id in team_ids.items():   # these are the goals that also live on the team board
            if key in gnums:
                conn.execute("UPDATE goals SET source='team', team_id=? WHERE gnum=? OR birth=?", (team_id, gnums[key], gnums[key]))
        set_meta(conn, "demo", lang)
    return {"goals": conn.execute("SELECT COUNT(*) FROM goals").fetchone()[0],
            "entries": conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0], "actions": n, "skipped": skipped}


def reset_main(now: datetime) -> dict:
    """Empty the main board to start your own: back the whole database up to backups/ first, then recreate it
    (config and person are kept) and rebuild the practice database."""
    from app.sample import build_practice

    main = db_path(False)
    backups = data_dir() / "backups"
    backups.mkdir(parents=True, exist_ok=True)
    backup: Path | None = backups / f"board-{now.astimezone(settings.tz()).strftime('%Y%m%d-%H%M%S')}.sqlite"
    person = ""
    floor: dict[str, int] = {}
    if main.exists():
        src = open_db(main)
        person = get_meta(src, "person") or ""
        floor = birth_floor(src)   # how far birth numbers got: after the reset they keep counting instead of restarting at 1
        dst = sqlite3.connect(str(backup))
        src.backup(dst)  # sqlite's own backup API also carries what is still in the WAL
        dst.close()
        src.close()
        for suffix in ("", "-wal", "-shm"):
            Path(str(main) + suffix).unlink(missing_ok=True)
    else:
        backup = None
    conn = open_db(main)
    with conn:
        if person:
            set_meta(conn, "person", person)
        for letter, seq in floor.items():
            if seq:
                set_meta(conn, f"birth_seq_{letter}", str(seq))
    conn.close()
    practice = build_practice(now)
    return {"backup": str(backup) if backup else "", "main": str(main), "practice": str(practice)}
