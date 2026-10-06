"""虚构的示例数据（中、英各一套），让刚装好的看板有东西可看。

    python3 -m team_board seed --lang zh        # 只在空的正式库上灌
    python3 -m team_board seed --practice       # 重做练手库并灌进去（不碰正式库）

虚构的公司：三人初创团队，做宠物照护 App「爪印 / Pawprint」。人、线、环节取配置里的（按顺序：第一个 owner
是发起人，其后两位成员是两位执行人），所以用 `init` 生成的初始配置灌出来就是 林夏 / 周行 / 苏禾（Alex / Ben / Chloe）。
日期一律按「灌入当天」往前推算。灌进去的是普通目标（这家虚构公司的「正式看板」），不标示例。

六个目标各自演示一种协作情形：
- G1 会员订阅上线：发起人只做业务环节，执行拆成几个整包（其中一块跨到运营线）；下游声明依赖，
  上游改期后晚于下游需要它的日子 → 提前亮出「依赖冲突」；下游做到一半「等依赖」暂停。
- G2 新用户引导改版：一个人从业务做到测试，环节重叠、回头再进同一环节；带来源号（个人看板推上来的）。
- G3 宠物医院合作落地页：已完成，有「做什么 / 做了什么」。
- G4 崩溃率降到 0.5% 以下：长期负责、没有完成日；负责人自己在下面拆带日期的块给自己，其中一块改过计划日、已延期。
- G5 新协作方式落地：笼统的事，不拆环节，只看起止。
- G6 智能喂养提醒 1.0：一个目标拆三块——一块整包给别人、一块不用等谁、一块的开发要等另一块做完
  （做完产品就「等依赖」暂停，对方完成后恢复），最后整体拖过了计划日。
"""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, time, timedelta

from team_board import config
from team_board.board.actions import Who, apply_action
from team_board.board.model import iso, tz, tz_day, utc_now
from team_board.board.state import fold
from team_board.board.store import load_events

LANGS = ("zh", "en")

TEXT: dict[str, dict[str, str]] = {
    "zh": {
        "g1": "会员订阅上线",
        "g1.note": "母题由发起人{owner}负责：发起、做业务环节、检查点验收、最后验收、兜底。检查点：会员页面的产品方案做完，"
                   "{owner}验收一次再往下做。执行拆成三个整包：支付与订阅后端（{m1}）、会员页面（{m2}）、后台价格配置（{m2}，挂在运营线）。"
                   "真实用户能完成一次订阅、后台看得到订单，算完。",
        "g1.1": "支付与订阅后端",
        "g1.1.note": "{m1}整包：接支付渠道、订阅状态与续费、给会员页面用的订阅接口。环节由他自己定、自己录。",
        "g1.1.due_reason": "支付渠道的商户审核比预想慢，后端联调要晚三天",
        "g1.2": "会员页面：从产品到测试",
        "g1.2.note": "{m2}一个人从产品方案做到测试，不按环节拆；产品方案做完{owner}验收一次。"
                     "开发要等支付与订阅后端的接口，测试要有后台价格配置可用。",
        "g1.2.pause": "等订阅接口，接上真数据才能定稿",
        "g1.3": "后台价格配置",
        "g1.3.note": "运营后台里配会员价格与套餐。它和上线后的持续运营有关，所以挂在运营线，仍属于「会员订阅上线」。",
        "g2": "新用户引导改版",
        "g2.note": "重做新用户第一次打开 App 到添加第一只宠物的流程。{owner}一个人从业务做到测试。"
                   "添加宠物的完成率到 60%、次日留存不低于改版前，算完。",
        "g3": "宠物医院合作落地页",
        "g3.note": "给合作宠物医院用的落地页：医院扫码进来能看到合作权益并留下联系方式。上线后一周内收到 10 家医院的有效线索，算完。",
        "g3.done": "合作医院落地页上线：扫码就能看到合作权益\n医院可以在线提交合作意向，提交后自动通知运营\n按城市展示已合作的医院",
        "g4": "崩溃率降到 0.5% 以下",
        "g4.note": "{m1}长期对 App 崩溃率负责，没有完成日。崩溃率数字本身看线上监控，看板只记他为此做的具体事——做什么、怎么拆由他自己定。",
        "g4.1": "启动闪退定位与修复",
        "g4.1.note": "{m1}自己拆的：先把上报最多的启动闪退修掉。",
        "g4.1.done": "修复了旧机型上启动即闪退的问题\n启动时不再因为读取损坏的本地缓存而崩溃",
        "g4.2": "崩溃日报自动发到团队群",
        "g4.2.note": "{m1}自己拆的：每天自动发前一天的崩溃数和前三名原因，不用人去查。",
        "g4.2.due_reason": "群机器人的权限申请比预想慢，先把日报内容做完",
        "g4.3": "崩溃率口径与周会看法",
        "g4.3.note": "{m1}自己拆的：定清楚崩溃率怎么算、周会看哪几个数。",
        "g5": "新协作方式落地",
        "g5.note": "让团队以后都按「一个人负责到底」的方式做事：谁负责，谁从头做到尾；卡住了在看板上说。笼统的事，不拆环节，只看起止。",
        "g6": "智能喂养提醒 1.0",
        "g6.note": "按宠物的年龄和体重，到点提醒主人喂食。拆三块：推送服务与接口（{m1}整包）、App 提醒页面（{owner}，不用等接口）、"
                   "提醒调度逻辑（{owner}，开发要等推送服务做完）。",
        "g6.1": "推送服务与接口",
        "g6.1.note": "{m1}整包负责；接口约定和假接口先做，别的块不用干等。",
        "g6.1.done": "推送服务上线：按用户时区定时推送\n提供提醒的增、删、改、查接口",
        "g6.2": "App 提醒页面",
        "g6.2.note": "不依赖推送服务，{owner}从产品一路做到测试；测出问题回头改产品，测试同时继续。",
        "g6.2.done": "新增「喂养提醒」页面：可以给每只宠物设每天的喂食时间\n提醒可以单独开关",
        "g6.3": "提醒调度逻辑",
        "g6.3.note": "开发整个在推送服务完成之后：先做产品，然后等依赖；对方完成后才开发、测试。",
        "g6.3.pause": "等推送服务与接口",
        "n1": "支付回调联调通过了，订阅续费今天开始做。不过支付渠道的商户审核比预想慢，后端大概要晚三天。",
        "n1.summary": "把「支付与订阅后端」的计划完成日往后改了三天，原因写了商户审核慢",
        "n2": "会员页的 UI 第二版出完了，现在卡在订阅接口上，接上真数据才能定稿。",
        "n3": "周会定了：下个迭代做「宠物体重记录」，{m2}负责，大概两周，{m1}配合接口。",
    },
    "en": {
        "g1": "Launch paid membership",
        "g1.note": "{owner} initiated this and owns the parent goal: the business stage, the checkpoint review, final sign-off, "
                   "and anything that falls through the cracks. Checkpoint: {owner} reviews the membership-screen spec once "
                   "before work continues. Execution is split into three whole packages: payments & subscription backend ({m1}), "
                   "membership screens ({m2}), and admin pricing settings ({m2}, on the Operations line). "
                   "Done when a real user can subscribe and the order shows up in the admin.",
        "g1.1": "Payments & subscription backend",
        "g1.1.note": "{m1} owns the whole package: payment provider, subscription state and renewals, and the subscription API "
                     "the membership screens need. Stages are his to decide and record.",
        "g1.1.due_reason": "Merchant review at the payment provider is slower than expected; backend integration slips three days",
        "g1.2": "Membership screens, product to test",
        "g1.2.note": "{m2} takes this from product spec through testing, not split by stage. {owner} reviews the spec once. "
                     "Dev needs the subscription API from the backend; testing needs the admin pricing settings.",
        "g1.2.pause": "Waiting for the subscription API; can't finalize without real data",
        "g1.3": "Admin pricing settings",
        "g1.3.note": "Set membership prices and plans in the admin. It ties into day-to-day operations after launch, "
                     "so it sits on the Operations line while still belonging to “Launch paid membership”.",
        "g2": "New-user onboarding redesign",
        "g2.note": "Rework the flow from first launch to adding the first pet. {owner} does it end to end, business through test. "
                   "Done when 60% of new users finish adding a pet and day-1 retention is no worse than before.",
        "g3": "Vet-clinic partner landing page",
        "g3.note": "A landing page for partner vet clinics: scan a code, see the partner benefits, leave contact details. "
                   "Done when 10 clinics send a valid lead within a week of launch.",
        "g3.done": "Partner landing page is live: scan the code to see partner benefits\n"
                   "Clinics can apply online, and operations is notified right away\nPartner clinics are listed by city",
        "g4": "Crash rate under 0.5%",
        "g4.note": "{m1} owns the app's crash rate for the long run, so there is no finish date. The number itself lives in "
                   "production monitoring; the board only tracks the concrete work he does for it. What to do and how to split it is his call.",
        "g4.1": "Startup crash fix",
        "g4.1.note": "Split off by {m1} himself: fix the most-reported crash on startup first.",
        "g4.1.done": "Fixed the crash on launch on older devices\nA corrupted local cache no longer crashes the app at startup",
        "g4.2": "Daily crash digest to team chat",
        "g4.2.note": "Split off by {m1} himself: post yesterday's crash count and top three causes every day, so nobody has to look it up.",
        "g4.2.due_reason": "Getting bot permission for the team chat is taking longer than expected; finishing the digest content first",
        "g4.3": "Crash-rate definition for weekly review",
        "g4.3.note": "Split off by {m1} himself: pin down how crash rate is calculated and which numbers the weekly review looks at.",
        "g5": "Roll out the new way of working",
        "g5.note": "Get the team working end to end: whoever owns a goal carries it from start to finish, and says so on the board when stuck. "
                   "A broad goal: no stages, just start and end.",
        "g6": "Smart feeding reminders 1.0",
        "g6.note": "Remind owners when to feed, based on each pet's age and weight. Three parts: push service & API ({m1}, whole package), "
                   "reminder screens ({owner}, no need to wait for the API), and reminder scheduling ({owner}, dev has to wait for the push service).",
        "g6.1": "Push service & API",
        "g6.1.note": "{m1} owns the whole package. API contract and a mock API come first, so nobody else sits waiting.",
        "g6.1.done": "Push service is live: scheduled pushes in each user's time zone\nAPI to create, edit, list and delete reminders",
        "g6.2": "Reminder screens",
        "g6.2.note": "Doesn't depend on the push service. {owner} takes it from product through test; when testing finds a problem, "
                     "product gets reopened while testing carries on.",
        "g6.2.done": "New “Feeding reminders” screen: set daily feeding times per pet\nEach reminder can be switched on or off",
        "g6.3": "Reminder scheduling",
        "g6.3.note": "All of dev comes after the push service is done: product first, then wait on the dependency; dev and test start once it lands.",
        "g6.3.pause": "Waiting for the push service & API",
        "n1": "Payment callbacks pass integration, and I'm starting on renewals today. But merchant review at the payment provider "
              "is slower than expected, so the backend will land about three days late.",
        "n1.summary": "Moved the due date of “Payments & subscription backend” out by three days; reason: slow merchant review",
        "n2": "Second round of the membership UI is done. I'm blocked on the subscription API now; can't finalize without real data.",
        "n3": "Decided at the weekly: next iteration we build “pet weight log”. {m2} owns it, roughly two weeks, {m1} helps with the API.",
    },
}


class SeedRefused(Exception):
    pass


def seed_demo(conn: sqlite3.Connection, lang: str, today: date | None = None) -> int:
    """往一份**空**库里灌示例数据，返回目标数。库里已有目标就拒绝（SeedRefused）。"""
    if lang not in LANGS:
        raise ValueError(f"lang must be one of {LANGS}")
    if fold(load_events(conn)).goals:
        raise SeedRefused()
    cfg = config.current()
    owner = cfg.default_person
    members = [p for p in cfg.persons if p.id != owner.id] or [owner]
    m1, m2 = members[0], members[1 % len(members)]
    names = {"owner": owner.name, "m1": m1.name, "m2": m2.name}
    tx = {k: v.format(**names) for k, v in TEXT[lang].items()}
    OWN, M1, M2 = Who(owner.id, "seed"), Who(m1.id, "seed"), Who(m2.id, "seed")

    def line(i: int) -> str:
        return cfg.lines[i % len(cfg.lines)]

    def stage(i: int) -> str:
        return cfg.stages[min(i, len(cfg.stages) - 1)]

    BIZ, PRODUCT, UI, DEV, TEST = (stage(i) for i in range(5))
    d0 = today or tz_day(utc_now())

    def at(base: int, day: float) -> datetime:
        """base：这个场景从「今天往前几天」开始；day：场景里的第几天（上午 10 点起算，可以带小数）。"""
        return datetime.combine(d0 - timedelta(days=base), time(10), tzinfo=tz()) + timedelta(days=day)

    def due(base: int, day: int) -> str:
        return str(d0 - timedelta(days=base) + timedelta(days=day))

    def act(who: Who, action: str, when: datetime, **params) -> int | None:
        # 记录时刻就取发生时刻：示例数据像是当时随手录的，不带「补录」标记
        params = {k: v if isinstance(v, bool) else str(v) for k, v in params.items()}
        r = apply_action(conn, action, {**params, "occurred_at": iso(when)}, who, when)
        return r.goal_id if r.goal_id is not None else r.event_ids[0]

    def stages_(who: Who, gid: int, base: int, plan: list[tuple[str, float, float | None]]) -> list[tuple]:
        # 配置里的环节不足五个时，几个环节会落到同一个名字上：同名而时间重叠的段并成一段（同一环节不能同时开两次）
        merged: list[list] = []
        for st, a, b in sorted(plan, key=lambda x: (x[0], x[1])):
            last = merged[-1] if merged and merged[-1][0] == st else None
            if last is not None and (last[2] is None or a <= last[2]):
                last[2] = None if last[2] is None or b is None else max(last[2], b)
            else:
                merged.append([st, a, b])
        out = []
        for st, a, b in sorted(merged, key=lambda x: x[1]):
            out.append((at(base, a), who, "start_stage", {"goal_id": gid, "stage": st}))
            if b is not None:
                out.append((at(base, b), who, "end_stage", {"goal_id": gid, "stage": st}))
        return out

    # 每个场景从今天往前几天开始。最晚的一步都落在昨天（含）以前，什么时候灌都不会「发生在将来」
    B1, B2, B3, B4, B5, B6 = 6, 8, 16, 11, 10, 33

    # ---- 先立六个顶层目标，编号就是 G1…G6；再立各自拆出来的块 ----
    g1 = act(OWN, "create", at(B1, 0), title=tx["g1"], line=line(0), owner=owner.id, due=due(B1, 10), note=tx["g1.note"])
    g2 = act(OWN, "create", at(B2, 0), title=tx["g2"], line=line(0), owner=owner.id, due=due(B2, 11), note=tx["g2.note"],
             source=f"{owner.letter}4")
    g3 = act(OWN, "create", at(B3, 0), title=tx["g3"], line=line(1), owner=owner.id, due=due(B3, 10), note=tx["g3.note"])
    g4 = act(OWN, "create", at(B4, 0), title=tx["g4"], line=line(0), owner=m1.id, long_term=True, note=tx["g4.note"])
    act(OWN, "create", at(B5, 0), title=tx["g5"], line=line(3), owner=owner.id, due=due(B5, 24), note=tx["g5.note"])
    g6 = act(OWN, "create", at(B6, 0), title=tx["g6"], line=line(0), owner=owner.id, due=due(B6, 24), note=tx["g6.note"])

    # G1：发起人做业务，执行拆成三个整包（后台价格配置跨到运营线）
    g11 = act(OWN, "create", at(B1, 0.3), title=tx["g1.1"], owner=m1.id, parent_id=g1, due=due(B1, 7), note=tx["g1.1.note"])
    g12 = act(OWN, "create", at(B1, 0.3), title=tx["g1.2"], owner=m2.id, parent_id=g1, due=due(B1, 10), note=tx["g1.2.note"])
    g13 = act(OWN, "create", at(B1, 0.3), title=tx["g1.3"], owner=m2.id, parent_id=g1, line=line(2), due=due(B1, 9),
              note=tx["g1.3.note"])
    # G4：长期负责的人自己在下面拆带日期的块给自己
    g41 = act(M1, "create", at(B4, 1), title=tx["g4.1"], owner=m1.id, parent_id=g4, due=due(B4, 8), note=tx["g4.1.note"])
    g42 = act(M1, "create", at(B4, 7), title=tx["g4.2"], owner=m1.id, parent_id=g4, due=due(B4, 9), note=tx["g4.2.note"])
    g43 = act(M1, "create", at(B4, 9), title=tx["g4.3"], owner=m1.id, parent_id=g4, due=due(B4, 13), note=tx["g4.3.note"])
    # G6：一个目标拆三块——推送服务整包给别人；提醒页面不用等谁；调度逻辑的开发要等推送服务
    g61 = act(OWN, "create", at(B6, 3), title=tx["g6.1"], owner=m1.id, parent_id=g6, due=due(B6, 17), note=tx["g6.1.note"])
    g62 = act(OWN, "create", at(B6, 3), title=tx["g6.2"], owner=owner.id, parent_id=g6, due=due(B6, 20), note=tx["g6.2.note"])
    g63 = act(OWN, "create", at(B6, 3), title=tx["g6.3"], owner=owner.id, parent_id=g6, due=due(B6, 25), note=tx["g6.3.note"])

    steps: list[tuple] = []
    # ---- G1 ----
    steps += stages_(OWN, g1, B1, [(BIZ, 0, 0.3)])
    # 依赖是「做到某环节时需要另一个目标完成」：会员页面的开发要等后端，测试要等后台价格配置
    steps += [(at(B1, 0.3), OWN, "declare_dependency", {"goal_id": g12, "on_goal": g11, "at_stage": DEV, "need_by": due(B1, 8)}),
              (at(B1, 0.3), OWN, "declare_dependency", {"goal_id": g12, "on_goal": g13, "at_stage": TEST})]
    steps += stages_(M1, g11, B1, [(PRODUCT, 0.5, 1.5), (DEV, 1.5, None)])
    # 上游改期：新日子晚于下游需要它的那天 → 看板提前亮出「依赖冲突」
    steps += [(at(B1, 4), M1, "change_due", {"goal_id": g11, "due": due(B1, 10), "reason": tx["g1.1.due_reason"]})]
    steps += stages_(M2, g12, B1, [(PRODUCT, 0.4, 2.5), (UI, 2, 4), (PRODUCT, 4, 4.6), (UI, 4.5, None)])
    steps += [(at(B1, 5), M2, "pause", {"goal_id": g12, "kind": "dependency", "depends_on": g11, "note": tx["g1.2.pause"]})]
    steps += stages_(M2, g13, B1, [(PRODUCT, 1, 2), (DEV, 3, None)])
    # ---- G2：一个人做全流程，环节重叠，测试期间回头再进一次产品 ----
    steps += stages_(OWN, g2, B2, [(BIZ, 0, 1), (PRODUCT, 1, 3), (UI, 2, 4), (DEV, 4, None), (TEST, 6, None), (PRODUCT, 6.5, 7.2)])
    # ---- G3：上周已完成 ----
    steps += stages_(OWN, g3, B3, [(PRODUCT, 0, 2), (DEV, 2, 7), (TEST, 6, 9)])
    steps += [(at(B3, 9), OWN, "complete", {"goal_id": g3, "done_what": tx["g3.done"]})]
    # ---- G4：三块各自记环节；第二块改过计划日（原定的日子已过 → 显示延期）----
    steps += stages_(M1, g41, B4, [(DEV, 1, 6), (TEST, 5, 7)])
    steps += [(at(B4, 7), M1, "complete", {"goal_id": g41, "done_what": tx["g4.1.done"]})]
    steps += stages_(M1, g42, B4, [(DEV, 7, None)])
    steps += [(at(B4, 8.5), M1, "change_due", {"goal_id": g42, "due": due(B4, 16), "reason": tx["g4.2.due_reason"]})]
    steps += stages_(M1, g43, B4, [(PRODUCT, 9, None)])
    # ---- G6 ----
    steps += stages_(OWN, g6, B6, [(BIZ, 0, 3)])
    steps += [(at(B6, 3), OWN, "declare_dependency", {"goal_id": g63, "on_goal": g61, "at_stage": DEV})]
    steps += stages_(M1, g61, B6, [(PRODUCT, 3, 5), (DEV, 5, 16), (TEST, 14, 18)])
    steps += [(at(B6, 18), M1, "complete", {"goal_id": g61, "done_what": tx["g6.1.done"]})]
    steps += stages_(OWN, g62, B6, [(PRODUCT, 3, 7), (UI, 5, 9), (DEV, 8, 16), (TEST, 14, 19), (PRODUCT, 15, 16)])
    steps += [(at(B6, 19), OWN, "complete", {"goal_id": g62, "done_what": tx["g6.2.done"]})]
    steps += stages_(OWN, g63, B6, [(PRODUCT, 3, 6)])
    steps += [(at(B6, 6), OWN, "pause", {"goal_id": g63, "kind": "dependency", "depends_on": g61, "note": tx["g6.3.pause"]}),
              (at(B6, 18), OWN, "resume", {"goal_id": g63})]
    steps += stages_(OWN, g63, B6, [(DEV, 18, 28), (TEST, 24, None), (DEV, 30, None)])

    for when, who, action, params in sorted(steps, key=lambda s: s[0]):     # 稳定排序：同一时刻的按上面写的先后
        act(who, action, when, **params)

    # ---- 口述记录：一条已录入、两条待录入 ----
    n1 = act(M1, "add_note", at(B1, 3.9), text=tx["n1"], goal_id=g11)
    act(M1, "resolve_note", at(B1, 4.02), note_id=n1, summary=tx["n1.summary"])
    act(M2, "add_note", at(B1, 5.1), text=tx["n2"], goal_id=g12)
    act(OWN, "add_note", at(B1, 5.2), text=tx["n3"])
    return len(fold(load_events(conn)).goals)
