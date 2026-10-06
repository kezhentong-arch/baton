"""看板的常量与时间工具。

时间规矩：存带偏移的 UTC，切日和截止时刻显式用配置里的主时区，不依赖宿主机时区——
服务器和各人电脑常常不在一个时区，隐式本地时间会让日期悄悄错一天。

人、线、环节都来自配置（team_board.config），这里只提供取值的小函数。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from team_board import config
from team_board.i18n import t, unit


def tz() -> ZoneInfo:
    return config.current().tz


def tz_note() -> str:
    """跟在时刻后面的时区说明：「（上海）」/ " (Berlin)"。"""
    return t("tz.note", label=config.current().zone.label)


def people() -> dict[str, str]:
    return config.current().people


def lines() -> tuple[str, ...]:
    return config.current().lines


def stages() -> tuple[str, ...]:
    return config.current().stages


def repos() -> tuple[str, ...]:
    return config.current().repos


def is_team_owner(person: str) -> bool:
    """owner 角色：立项、拆给别人、换负责人、放弃、定版本计划只有他们能做（可以有多个）。"""
    return person in config.current().owners


def person_name(pid: str, missing: str | None = None) -> str:
    return people().get(pid, t("person.unassigned") if missing is None else missing)


PAUSE_KEYS: tuple[str, ...] = ("dependency", "external")


def pause_kinds() -> dict[str, str]:
    return {k: t(f"pause.{k}") for k in PAUSE_KEYS}


# 看板从立项开始：提议、待立项在周会或私下讨论，属于流程之外。
# approved 与 active 的区别只是有没有开始记环节，对人都叫「进行中」
STATUSES: tuple[str, ...] = ("approved", "active", "done", "abandoned")


def status_label(status: str) -> str:
    return t(f"status.{status}")


# 看板不设优先级：立项与指派本身就是排序结果；单人全流程下的轻重是个人的权衡。旧事件里的 priority 字段读到也不显示。

# 时间线缩放：时间线是一整条，可以左右拖；缩放只决定「一屏看多长」，内容在哪一档都是全的。
# 最小一屏一天（计划完成可以到小时，缩到这档能看到几点）、最大一个季度。键 → 一屏几天
ZOOM_DAYS: dict[str, int] = {"day": 1, "week": 7, "2week": 14, "month": 30, "quarter": 91}
HOUR_TICK_STEP = 2            # 「一天」档的小时刻度：每 2 小时一条
DEFAULT_ZOOM = "week"


def zooms() -> dict[str, tuple[str, int]]:
    """键 → (名称, 一屏几天)"""
    return {k: (t(f"zoom.{k}"), n) for k, n in ZOOM_DAYS.items()}


def gtag(goal_id: int) -> str:
    """目标在看板上的编号写法：G17。G 是 goal，和 GitHub 单的「#174」分得开。
    号是立项时按先后发的，不变、不回收、不表示优先级。"""
    return f"G{goal_id}"


STALE_STAGE_DAYS = 5          # 环节超过 5 天没变、关联的单却有动静 → 标黄
SUBCONTRACT_WARN_DAYS = 7     # 分包等待超过 7 天 → 提示考虑改成子目标
SYNC_STALE_MINUTES = 30       # GitHub 数据超过 30 分钟没更新 → 醒目提示
SYNC_INTERVAL_SECONDS = 600   # 后台每 10 分钟同步一次
BACKFILL_GRACE = timedelta(hours=1)       # 发生时间早于记录时间超过 1 小时 → 标「补录」
FUTURE_TOLERANCE = timedelta(minutes=5)   # 发生时间最多允许比服务器时间晚 5 分钟（时钟误差）


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_ts(s: str) -> datetime:
    """带偏移的 ISO 串 → aware datetime。没有时区的串直接拒绝，不猜。"""
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError(f"timestamp without UTC offset: {s!r}")
    return dt


def iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        raise ValueError("refusing to store a timestamp without a timezone")
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def parse_day(s: str) -> date:
    return date.fromisoformat(s)


def day_deadline(d: date) -> datetime:
    """主时区某个日期的最后一刻，用作「预计完成日」的截止时刻。"""
    return datetime.combine(d, time(23, 59, 59), tzinfo=tz())


@dataclass(frozen=True, order=True)
class Due:
    """计划完成：到天或到小时（「周五上午 8 点前」只落成一个日期不够，放大也看不到几点）。
    只写日期的落在当天 23:59；写了时刻的落在那个时刻。全部按主时区。
    记录里存的是人写的字符串（2026-10-02 或 2026-10-02 08:00）。"""
    at: datetime                                  # 截止时刻（主时区，带时区）；比较、排序都按它
    timed: bool = field(default=False, compare=False)   # 人写了几点

    @classmethod
    def parse(cls, s: str) -> "Due":
        s = s.strip().replace("T", " ")
        if len(s) == 10:
            return cls(day_deadline(date.fromisoformat(s)), False)
        if len(s) == 16:
            return cls(datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=tz()), True)
        raise ValueError(t("err.due_format_raw", value=repr(s)))

    @property
    def day(self) -> date:
        return self.at.date()

    def __str__(self) -> str:
        return self.at.strftime("%Y-%m-%d %H:%M" if self.timed else "%Y-%m-%d")

    @property
    def short(self) -> str:
        """图上和名称下面那行的写法：10-02 或 10-02 08:00。"""
        return self.at.strftime("%m-%d %H:%M" if self.timed else "%m-%d")


def late_text(deadline: datetime, end: datetime) -> str:
    """延期多少的人话，按实际超出多久（和配套的个人看板一字不差）。不满 1 小时不算；不满 1 天四舍五入到小时；
    不满 10 天保留一位小数；10 天起四舍五入到整天。空串 = 没延期。
    怎么做到和浏览器里的 JS 一字不差：先取整到毫秒、用一次整数除法得到和 JS 一样的浮点数，
    再按它的精确值逢五进一（= JS 的 Math.round / toFixed）。不能 int(d * 10 + 0.5)：1.15 天的浮点数其实是 1.1499…，
    JS 写 1.1，乘 10 后却正好 11.5 进成 1.2；Python 的 round 和格式化又是逢五取偶。"""
    late = end - deadline
    ms = (late.days * 86400 + late.seconds) * 1000 + late.microseconds // 1000
    if ms < 3600_000:
        return ""
    if ms < 86400_000:
        return unit(_half_up(ms / 3600_000, "1"), "hour")
    d = ms / 86400_000
    return unit(_half_up(d, "1") if d >= 10 else _half_up(d, "0.1"), "day")


def _half_up(x: float, step: str) -> Decimal:
    return Decimal(x).quantize(Decimal(step), ROUND_HALF_UP)   # Decimal(x) 是浮点数的精确值，不先变成字符串


def tz_text(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    return dt.astimezone(tz()).strftime("%m-%d %H:%M")


def tz_day(dt: datetime) -> date:
    return dt.astimezone(tz()).date()


def days(td: timedelta) -> float:
    return round(td.total_seconds() / 86400, 1)


def duration_text(td: timedelta) -> str:
    """页面上时长的人话：不满 1 小时写分钟，不满 1 天写小时，满 1 天写天，小时和天保留一位小数（整数不带「.0」）。
    一律按天保留一位小数的话，几十分钟的环节会显示成「0.0 天」。接口里的天数（stage_days 等）照旧给数字，只改页面写法。"""
    sec = td.total_seconds()
    if sec < 60:
        return t("dur.under_minute")
    if sec < 3600:
        return t("dur.minutes", n=int(sec // 60))
    if sec < 86400:
        return unit(f"{round(sec / 3600, 1):g}", "hour")
    return unit(f"{round(sec / 86400, 1):g}", "day")


def gh_due_day(dt: datetime) -> date:
    """GitHub 里程碑的截止日存成「那天 00:00 UTC」。按 UTC 取日期才是 GitHub 上看到的那天；
    换成别的时区可能变成前一天（例：2026-07-22T00:00Z 在 UTC-7 是 07-21 17:00）。"""
    return dt.astimezone(timezone.utc).date()
