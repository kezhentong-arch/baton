"""时间线几何：每一行、每段色块的位置在这里算好，模板只负责画。

时间线是一整条，覆盖所有目标从开始到计划完成（内容在哪一档缩放都要是全的，
左右拖动看别的时间段）。位置一律是「占整条宽度的百分比」；一屏看多长（缩放）、拖到哪，都在浏览器里做，
折叠也是，不刷新页面。"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from team_board import config
from team_board.board.issues import GhData
from team_board.board.model import (HOUR_TICK_STEP, Due, late_text, pause_kinds, people, person_name, stages,
                                    status_label, tz, tz_day, tz_note, tz_text)
from team_board.board.state import Board, Goal, VersionTrack, delay_text
from team_board.i18n import t

ROW_H = 40


def stage_fill(stage: str) -> str:
    """环节的颜色：第几个环节就是第几个颜色变量（颜色本身在配置里，页面样式里展开）。"""
    return f"var(--st{stages().index(stage)})"


@dataclass
class Piece:
    x: float                  # 左边，百分比
    w: float                  # 宽度，百分比
    fill: str
    label: str
    title: str
    hatched: bool = False
    lane: int = 0             # 第几条细道；-1 = 覆盖整行（暂停）
    # 「还在做」：没做完的事从「现在」往右接一条淡虚线，延到整条右端，
    # 拖到未来几天每行都有东西，不再像「这天没事」。开着的环节同色，没分环节灰色
    future: bool = False


@dataclass
class Mark:
    """计划完成日竖线：基准日实线，改期后的日期虚线，旁边写上日期（光一条白线看不懂）。"""
    x: float
    label: str
    replan: bool = False

    @property
    def flip(self) -> bool:
        """贴近整条的右端时，日期写在竖线左边，免得被截掉。"""
        return self.x > 97


@dataclass
class Tick:
    """每天一个刻度；显示哪些（每天 / 只周一）由浏览器按缩放档位决定。"""
    x: float
    day: str                  # 09-28
    weekday: str              # 一 … 日
    monday: bool


@dataclass
class HourTick:
    """「一天」档的小时刻度（计划到小时后要看得出几点）。"""
    x: float
    label: str                # 08:00


@dataclass
class Row:
    kind: str                 # version | goal
    title: str
    href: str = ""
    note: str = ""
    full_title: str = ""
    pieces: list[Piece] = field(default_factory=list)
    marks: list[Mark] = field(default_factory=list)
    overflow: tuple[float, float] | None = None     # 延期红框 (左, 宽)
    start_x: float | None = None                    # 开始的位置（图上写「开始 MM-DD」）
    start_text: str = ""      # 名称下面一行：开始 09-28 · 计划 10-02 · 延期 3 天——拖到哪都看得到
    plan_text: str = ""
    late: str = ""            # 延期多少的人话：3 小时 / 2 天；空 = 没延期
    life: tuple[float, float] | None = None         # 有环节记录的目标：底下一道细线，从立项到现在（或结束）
    h: float = ROW_H          # 这一行的高度（几个环节同时进行时，每个环节一条细道，行会变高）
    bar_h: float = 26
    depth: int = 0            # 第几层（目标 → 拆出来的子目标，可以多层）
    fold_key: str = ""        # 有下层时可折叠：G:<目标 id>
    anc: list[str] = field(default_factory=list)    # 上面所有能折叠它的开关（线、各层上层目标）
    gid: str = ""             # G17：目标编号，全站同一个写法
    source: str = ""          # A24：出生号，行上跟在编号后面的小字，和个人看板那一行对得上；团队看板直接立的没有
    owner: str = ""           # 负责人名字，名字后面的小块
    owner_key: str = ""       # 人的 id，取圆点颜色
    fam: str = ""             # 跨线家族：同一个业务目标拆到几条线时，所有块共用一个底色
    fam_tint: int = 0         # 第几种底色
    belongs: str = ""         # 跨线的子目标：属于 G17 <上层标题>
    elsewhere: str = ""       # 有块在别的线：另 1 块在 <线名>
    sample: bool = False      # 示例：示例看板上和真实目标放在一起，这一行标「示例」
    match: bool = False       # 按人筛选时：这行是他的事（不是为了带出路径的上层）
    people: list[tuple[str, str]] = field(default_factory=list)   # 这个目标涉及的人（负责人 + 各环节执行人）：收起时上层要列出来
    # 负责人以外还涉及谁（看板是为协作准备的，母任务和子任务都要一直看得见谁参与）：
    # 自己环节里别人做的段 + 下面所有子任务（含跨线的）的负责人与执行人，去掉本行负责人，按出现顺序
    others: list[tuple[str, str]] = field(default_factory=list)
    # 已结束的目标 / 版本：名称下面一行写「已完成 10-01」，图上在完成那一刻画 ✓；
    # 放弃的写「已放弃」画 ✕（绿=完成）
    ended: str = ""           # done | abandoned | ""
    ended_text: str = ""      # 已完成 10-01 / 已放弃 10-01
    ended_x: float | None = None
    version_name: str = ""    # 这个目标挂的版本（人话名字），只在版本挂上来的那一层显示（上层没挂、自己挂了）
    version_href: str = ""
    # 没做完、眼下又没有环节开着的（等别人、暂停）：在底下细寿命线的位置接一段灰虚线（「还在做」），保证每行没做完的在未来都有东西
    life_future: tuple[float, float] | None = None
    # 版本行：这次发布装着哪些目标（编号、名字、链接），点一下进那个目标
    # （版本只在装着多个目标时才成行，成行就要看得出装了什么）
    carried: list[tuple[str, str, str]] = field(default_factory=list)
    span: tuple[float, float] = (0.0, 100.0)   # 这一行有内容的范围（立项 → 结束），浏览器按窗口决定已结束的行要不要显示


@dataclass
class Band:
    line: str
    note: str
    fold_key: str             # L:<线>；这条线没有内容时为空
    rows: list[Row]
    sample: bool = False
    mark: str = ""            # ①
    color: str = ""           # 线的颜色：标题行和左侧色带


@dataclass
class Timeline:
    start: date
    end: date
    ticks: list[Tick]
    today_x: float | None
    bands: list[Band]
    hours: list[HourTick] = field(default_factory=list)

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1


@dataclass
class LineGroup:
    line: str
    note: str
    versions: list[tuple[str, list[Goal]]]
    loose: list[Goal]
    sample: bool = False      # 示例区：演示用的假设数据，单独一区放在各条线后面


class Scale:
    def __init__(self, start: date, end: date):
        self.t0 = datetime.combine(start, time(0), tzinfo=tz())
        self.t1 = datetime.combine(end + timedelta(days=1), time(0), tzinfo=tz())
        self.span = (self.t1 - self.t0).total_seconds()

    def x(self, dt: datetime) -> float:
        dt = min(max(dt, self.t0), self.t1)
        return round((dt - self.t0).total_seconds() / self.span * 100, 3)

    def day_x(self, d: date) -> float:
        return self.x(datetime.combine(d, time(0), tzinfo=tz()))

    def inside(self, dt: datetime) -> bool:
        return self.t0 <= dt <= self.t1

    def visible(self, a: datetime, b: datetime) -> bool:
        return b > self.t0 and a < self.t1


def _short(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def unfinished(g: Goal) -> bool:
    return g.closed_at is None and g.status not in ENDED


def future_piece(now: datetime, sc: Scale, fill: str, title: str, lane: int = 0) -> Piece | None:
    """从「现在」到整条右端的虚线；现在已经在整条之外就不画。"""
    if not sc.inside(now):
        return None
    x = sc.x(now)
    return Piece(x, round(100 - x, 3), fill, "", title, lane=lane, future=True)


def goal_pieces(g: Goal, now: datetime, sc: Scale) -> tuple[list[Piece], int]:
    """一个目标的色块。新方式下几个环节可以同时进行：每个用到的环节一条细道，上下排开，
    重叠一眼可见；暂停画成覆盖整行的斜线。返回 (色块, 细道数)。
    没做完的在「现在」之后接虚线（开着的环节同色；没分环节灰色），见 Piece.future。"""
    until = g.closed_at or now
    if not g.spans:
        # 没分环节：笼统的事项、按旧方式做且历史环节不追溯的目标，或刚立项还没开始记环节。
        # 只画从立项到现在（或结束）的一根灰条
        out = []
        if g.approved_at is not None and sc.visible(g.approved_at, until):
            x1, x2 = sc.x(g.approved_at), sc.x(until)
            out.append(Piece(x1, round(x2 - x1, 3), "var(--ver)", t("tl.no_stages"),
                             t("tl.no_stages_tip", start=tz_text(g.approved_at),
                               end=tz_text(g.closed_at) if g.closed_at else t("tl.now"), tz=tz_note())))
        if unfinished(g):
            fut = future_piece(now, sc, "var(--ver)", t("tl.future_no_stages"))
            if fut:
                out.append(fut)
        return out, 1
    used = [st for st in stages() if any(sp.stage == st for sp in g.spans)]
    lane = {st: i for i, st in enumerate(used)}
    out: list[Piece] = []
    for sp in g.spans:
        a, c = sp.start, sp.end or until
        if not sc.visible(a, c):
            continue
        x1, x2 = sc.x(a), sc.x(c)
        if x2 - x1 < 0.15:
            x2 = x1 + 0.15           # 很短的一段也留一道细线，不让它凭空消失
        who = "" if sp.executor == g.owner else f"·{person_name(sp.executor, sp.executor)}"
        end_txt = tz_text(sp.end) if sp.end else t("tl.running")
        out.append(Piece(x1, round(x2 - x1, 3), stage_fill(sp.stage), f"{sp.stage}{who}",
                         t("tl.stage_tip", stage=sp.stage, who=person_name(sp.executor, sp.executor),
                           start=tz_text(a), end=end_txt, tz=tz_note()),
                         lane=lane[sp.stage]))
        if sp.end is None and unfinished(g):
            fut = future_piece(now, sc, stage_fill(sp.stage),
                               t("tl.future_stage", stage=sp.stage, who=person_name(sp.executor, sp.executor)),
                               lane=lane[sp.stage])
            if fut:
                out.append(fut)
    for pz in g.pauses:
        a, c = pz.start, pz.end or until
        if sc.visible(a, c):
            x1, x2 = sc.x(a), sc.x(c)
            kind = pause_kinds()[pz.kind]
            out.append(Piece(x1, round(x2 - x1, 3), "", kind,
                             t("tl.pause_tip", kind=kind, start=tz_text(a), end=tz_text(c), tz=tz_note()), True, lane=-1))
    return out, max(1, len(used))


def _marks(baseline: Due | None, replans: list[Due], end: datetime | None,
           sc: Scale) -> tuple[list[Mark], tuple[float, float] | None]:
    """计划竖线画在截止时刻：只写日期的在当天 23:59，写了时刻的在那个小时。"""
    marks: list[Mark] = []
    over = None
    if baseline:
        dl = baseline.at
        if sc.inside(dl):
            marks.append(Mark(sc.x(dl), t("tl.plan", due=baseline.short)))
        if end and end > dl and sc.visible(dl, end):
            x1 = sc.x(dl)
            over = (x1, round(sc.x(end) - x1, 3))
    for d in replans:
        if sc.inside(d.at):
            marks.append(Mark(sc.x(d.at), t("tl.replan", due=d.short), True))
    return marks, over


def _plan_text(baseline: Due | None, latest: Due | None, long_term: bool = False) -> str:
    if latest is None:
        return t("due.long_term") if long_term else t("tl.plan_unset")
    return t("tl.plan", due=latest.short) + (t("tl.plan_was", due=baseline.short) if baseline and baseline != latest else "")


ENDED = ("done", "abandoned")


def _ended(status: str, closed_at: datetime | None, sc: Scale) -> tuple[str, str, float | None]:
    if status not in ENDED or closed_at is None:
        return "", "", None
    return status, f"{status_label(status)} {tz_day(closed_at):%m-%d}", sc.x(closed_at) if sc.inside(closed_at) else None


def _goal_row(g: Goal, now: datetime, sc: Scale, depth: int, root: str = "/board") -> Row:
    who = person_name(g.owner)
    title = g.title            # 不截断：名称列允许换两行，鼠标悬停有全名
    end = None if g.status == "abandoned" else (g.closed_at or now)
    marks, over = _marks(g.baseline_due, [d for _, d, _ in g.due_changes], end, sc)
    pieces, lanes = goal_pieces(g, now, sc)
    bar_h = 22 if lanes == 1 else 16
    life = None
    until = g.closed_at or now
    if g.spans and sc.visible(g.approved_at, until):
        # 环节之间的空档、拆给子目标以后，目标本身仍在进行——用一道细线把起止连起来
        x1 = sc.x(g.approved_at)
        life = (x1, round(sc.x(until) - x1, 3))
    # 涉及的人：负责人在前，再按出现顺序加各环节的执行人；收起来时上层行要写里面有谁
    keys = [g.owner] if g.owner else []
    keys += [s.executor for s in g.spans if s.executor not in keys]
    ended, ended_text, ended_x = _ended(g.status, g.closed_at, sc)
    # 没做完、眼下没有环节开着（等别人、暂停）：寿命线位置接灰虚线，每行没做完的在未来都有东西
    life_future = None
    if unfinished(g) and g.spans and not any(sp.end is None for sp in g.spans):
        fut = future_piece(now, sc, "var(--ver)", "")
        life_future = (fut.x, fut.w) if fut else None
    return Row("goal", title, f"{root}/goal/{g.id}",
               ended=ended, ended_text=ended_text, ended_x=ended_x, life_future=life_future,
               span=(sc.x(g.approved_at), sc.x(until)),
               full_title=f"{g.gnum}{' · ' + g.source if g.source else ''} {g.title} · {who} · {status_label(g.status)}",
               gid=g.gnum, source=g.source, owner=who, owner_key=g.owner, sample=g.sample,
               people=[(k, people()[k]) for k in dict.fromkeys(keys) if k in people()],
               pieces=pieces, marks=marks, overflow=over, life=life,
               start_x=sc.x(g.approved_at), start_text=t("tl.start", day=f"{tz_day(g.approved_at):%m-%d}"),
               plan_text=_plan_text(g.baseline_due, g.latest_due, g.long_term), late=delay_text(g, now),
               # 名字超过约 14 个汉字宽会换成两行（名称列 360px、带编号和人名），行要再高一点才放得下第二行信息
               bar_h=bar_h, h=max(ROW_H + 6, 24 + lanes * (bar_h + 3), 62 if text_width(g.title) > 14 - depth else 0),
               depth=depth)


def _version_row(ref: str, vt: VersionTrack | None, gh: GhData, now: datetime, sc: Scale, root: str = "/board") -> Row:
    repo, num = ref.split("#")
    m = gh.milestones.get((repo, int(num)))
    title = t("ver.title", name=m.title) if m else t("ver.title", name=t("ver.unsynced", ref=ref))
    start = m.created_at if m else (vt.tracked_at if vt else now)
    done_at = version_done_at(vt, m)
    end = done_at or now
    pieces = []
    if sc.visible(start, end):
        x1, x2 = sc.x(start), sc.x(end)
        tail = t("tl.done_at", time=tz_text(end)) if done_at else t("tl.now")
        pieces.append(Piece(x1, round(x2 - x1, 3), "var(--ver)", "",
                            t("tl.version_tip", title=title, start=tz_text(start), end=tail, tz=tz_note())))
    if done_at is None:                     # 没发布的版本同样「还在做」
        fut = future_piece(now, sc, "var(--ver)", t("tl.version_future", title=title))
        if fut:
            pieces.append(fut)
    plans = [d for _, d in vt.plans] if vt else []
    marks, over = _marks(plans[0] if plans else None, plans[1:], end, sc)
    late = late_text(plans[0].at, end) if plans else ""
    ended, ended_text, ended_x = _ended("done" if done_at else "", done_at, sc)
    return Row("version", _short(title, 22), version_href(ref, root),
               ended=ended, ended_text=ended_text, ended_x=ended_x, span=(sc.x(start), sc.x(end)),
               full_title=title, pieces=pieces, marks=marks, overflow=over, bar_h=14,
               start_text=t("tl.start", day=f"{tz_day(start):%m-%d}"),
               plan_text=_plan_text(plans[0] if plans else None, plans[-1] if plans else None),
               late=late, h=ROW_H + 6)


def text_width(s: str) -> float:
    """名称大约占几个汉字宽：汉字等全角字符算 1，拉丁字母、数字、空格算半个。"""
    return sum(1 if ord(ch) > 0x2E7F else 0.5 for ch in s)


def weekdays() -> list[str]:
    return t("weekdays").split(",")


def _ticks(start: date, end: date, sc: Scale) -> list[Tick]:
    out, names = [], weekdays()
    d = start
    while d <= end:
        out.append(Tick(sc.day_x(d), f"{d:%m-%d}", names[d.weekday()], d.weekday() == 0))
        d += timedelta(days=1)
    return out


def _hour_ticks(start: date, end: date, sc: Scale) -> list[HourTick]:
    """每天 02:00、04:00 … 22:00（整点 00:00 已有日刻度）。按主时区当地时刻取，夏令时切换那天照样对齐钟面。"""
    out = []
    d = start
    while d <= end:
        for h in range(HOUR_TICK_STEP, 24, HOUR_TICK_STEP):
            out.append(HourTick(sc.x(datetime.combine(d, time(h), tzinfo=tz())), f"{h:02d}:00"))
        d += timedelta(days=1)
    return out


def version_done_at(vt: VersionTrack | None, m) -> datetime | None:
    """版本什么时候完成：看板上标过就按看板；没标但 GitHub 里程碑已关闭，就按关闭时刻
    （不然里程碑关了、看板上版本行却还像在进行）。"""
    if vt and vt.done_at:
        return vt.done_at
    return m.closed_at if m is not None and m.closed_at else None


def version_name(ref: str, gh: GhData) -> str:
    """版本的人话名字 = GitHub 里程碑标题；还没同步到时退回原始写法并注明（留痕里只有仓库#编号看不懂）。"""
    repo, num = ref.split("#")
    m = gh.milestones.get((repo, int(num)))
    return m.title if m else t("ver.unsynced", ref=ref)


def version_carriers(b: Board, sample: bool) -> dict[str, list[Goal]]:
    """每个版本装着哪些目标：只数版本挂上来的那一层（上层没挂或挂的是别的版本、自己挂了），下层继承的不重复数——
    一个目标和它拆出的块都挂同一个版本算一个目标。示例目标只在示例看板上算。首页据此决定版本要不要单独成行。"""
    out: dict[str, list[Goal]] = {}
    for g in sorted(b.goals.values(), key=lambda g: g.id):
        if g.version and (sample or not g.sample) and (g.parent_id is None or b.goals[g.parent_id].version != g.version):
            out.setdefault(g.version, []).append(g)
    return out


def version_href(ref: str, root: str = "/board") -> str:
    repo, num = ref.split("#")
    return f"{root}/version?repo={repo}&number={num}"


def build_timeline(groups: list[LineGroup], b: Board, gh: GhData,
                   child_ok: Callable[[Goal], bool], now: datetime,
                   start: date, end: date,
                   match_ok: Callable[[Goal], bool] | None = None, root: str = "/board") -> Timeline:
    """按线分区；线内按拆分关系缩进（可以多层）。线和带下层的目标都可以折叠，
    折叠在浏览器里做：每行带上能折叠它的开关（anc）。

    跨线：一个业务目标拆到别的线的那块，留在它自己的线上显示，名字后面写「属于 G17 …」；
    整个家族（母题和它所有层级的块）共用一个底色，鼠标放上去一起亮；单线的目标树不加底色。"""
    sc = Scale(start, end)

    def kids(g: Goal) -> list[Goal]:
        return [b.goals[c] for c in g.children if child_ok(b.goals[c]) and b.goals[c].line == g.line]

    def root_of(g: Goal) -> Goal:
        while g.parent_id is not None:
            g = b.goals[g.parent_id]
        return g

    def family(g: Goal) -> list[Goal]:
        out, stack = [], [g]
        while stack:
            x = stack.pop()
            out.append(x)
            stack += [b.goals[c] for c in x.children]
        return out

    spanning = sorted({root_of(g).id for g in b.goals.values() if len({x.line for x in family(root_of(g))}) > 1})
    tint = {rid: i % 4 for i, rid in enumerate(spanning)}

    def involved(g: Goal) -> list[str]:
        """这个目标连同下面所有块涉及的人（负责人、各环节执行人），按出现顺序去重。"""
        keys: list[str] = []
        for x in family(g):
            for k in [x.owner, *(sp.executor for sp in x.spans)]:
                if k and k not in keys:
                    keys.append(k)
        return keys

    def add_goal(rows: list[Row], g: Goal, depth: int, anc: list[str]) -> None:
        row = _goal_row(g, now, sc, depth, root)
        row.anc = anc
        row.others = [(k, people()[k]) for k in involved(g) if k != g.owner and k in people()]
        row.match = bool(match_ok and match_ok(g))
        # 版本牌只在版本挂上来的那一层显示：上层没挂（或挂的是别的版本）、自己挂了；下层继承的不重复写
        if g.version and (g.parent_id is None or b.goals[g.parent_id].version != g.version):
            row.version_name, row.version_href = version_name(g.version, gh), version_href(g.version, root)
        top = root_of(g)
        if top.id in tint:
            row.fam, row.fam_tint = top.gnum, tint[top.id]
        if g.parent_id is not None and b.goals[g.parent_id].line != g.line:
            parent = b.goals[g.parent_id]
            row.belongs = t("tl.belongs", gnum=parent.gnum, title=parent.title)
        away = [b.goals[c] for c in g.children if b.goals[c].line != g.line and child_ok(b.goals[c])]
        if away:
            order = list(config.current().lines)
            elsewhere = sorted({c.line for c in away}, key=lambda ln: order.index(ln) if ln in order else len(order))
            row.elsewhere = t("tl.elsewhere", n=len(away), lines=t("sep").join(elsewhere))
        sub = kids(g)
        if sub:
            row.fold_key = f"G:{g.id}"
        rows.append(row)
        for c in sub:
            add_goal(rows, c, depth + 1, anc + [row.fold_key])

    bands = []
    carriers = version_carriers(b, any(grp.sample for grp in groups))
    for grp in groups:
        key = f"L:{grp.line}"
        rows: list[Row] = []
        for ref, goals in grp.versions:
            vrow = _version_row(ref, b.versions.get(ref), gh, now, sc, root)
            vrow.anc = [key]
            # 版本（GitHub 里程碑）本身没有负责人；挂它的目标有——版本行就写挂它的目标的负责人，几个人写几个
            # （不然已完成的版本行看不出是谁的任务）
            owners = [g.owner for g in b.goals.values() if g.version == ref and g.owner and (g.sample == grp.sample or not g.sample)]
            vrow.people = [(k, people()[k]) for k in dict.fromkeys(owners) if k in people()]
            vrow.carried = [(g.gnum, g.title, f"{root}/goal/{g.id}") for g in carriers.get(ref, [])]
            vrow.h += 15 * len(vrow.carried)          # 装着的目标一行一个（每行 15px），行要跟着高
            rows.append(vrow)
            for g in goals:
                add_goal(rows, g, 1, [key])
        for g in grp.loose:
            add_goal(rows, g, 0, [key])
        mark, color = config.current().line_marks.get(grp.line, ("", ""))
        bands.append(Band(grp.line, grp.note, key if rows else "", rows, grp.sample, mark, color))
    today_x = sc.x(now) if sc.inside(now) else None
    return Timeline(start, end, _ticks(start, end, sc), today_x, bands, _hour_ticks(start, end, sc))
