"""GitHub 单这一层（开了 GitHub 同步才有数据）：状态停留明细、分包等待、挪版本记录。只算时间，不数单。

哪些标签算「状态」、叫什么、到哪一步算分包已交付，都在配置的 github 一节里。"""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta

from team_board import config
from team_board.board.model import parse_ts
from team_board.board.state import Link
from team_board.i18n import t


def status_state(label: str) -> str | None:
    """标签 → 页面上写的状态；不是状态标签返回 None。前缀对得上、映射里却没有的，不猜，原样显示出来。"""
    gh = config.current().github
    for pattern, state in gh.label_map:
        if re.fullmatch(pattern, label):
            return state
    if gh.label_prefix and label.startswith(gh.label_prefix):
        return t("gh.unmapped_label", label=label)
    return None


@dataclass(frozen=True)
class GhIssue:
    repo: str
    number: int
    title: str
    url: str
    state: str
    created_at: datetime
    updated_at: datetime
    closed_at: datetime | None
    milestone_number: int | None
    parent_number: int | None
    labels: tuple[str, ...]


@dataclass(frozen=True)
class GhEvent:
    type: str
    at: datetime
    ref: str


@dataclass(frozen=True)
class GhMilestone:
    repo: str
    number: int
    title: str
    state: str
    due_on: datetime | None
    created_at: datetime
    closed_at: datetime | None


def _ts(v: str | None) -> datetime | None:
    return parse_ts(v) if v else None


class GhData:
    def __init__(self, conn: sqlite3.Connection):
        self.issues: dict[tuple[str, int], GhIssue] = {
            (r["repo"], r["number"]): GhIssue(
                r["repo"], r["number"], r["title"], r["url"], r["state"], parse_ts(r["created_at"]),
                parse_ts(r["updated_at"]), _ts(r["closed_at"]), r["milestone_number"],
                r["parent_number"], tuple(json.loads(r["labels"])))
            for r in conn.execute("SELECT * FROM gh_issues")}
        self.events: dict[tuple[str, int], list[GhEvent]] = {}
        # 同一秒的「摘下 v3.7、挂上 v3.8」只能靠写入顺序（= GitHub 返回顺序）区分先后
        for r in conn.execute("SELECT * FROM gh_events ORDER BY at, rowid"):
            self.events.setdefault((r["repo"], r["number"]), []).append(
                GhEvent(r["type"], parse_ts(r["at"]), r["ref"]))
        self.milestones: dict[tuple[str, int], GhMilestone] = {
            (r["repo"], r["number"]): GhMilestone(
                r["repo"], r["number"], r["title"], r["state"], _ts(r["due_on"]),
                parse_ts(r["created_at"]), _ts(r["closed_at"]))
            for r in conn.execute("SELECT * FROM gh_milestones")}

    def children_of(self, repo: str, number: int) -> list[GhIssue]:
        return sorted((i for i in self.issues.values()
                       if i.repo == repo and i.parent_number == number), key=lambda i: i.number)


def dwell(events: list[GhEvent], now: datetime) -> list[tuple[str, datetime, datetime | None]]:
    """状态标签的停留区间：(状态, 开始, 结束；还在这个状态则为 None)。"""
    out: list[tuple[str, datetime, datetime | None]] = []
    cur: tuple[str, datetime] | None = None
    for e in events:
        if e.type == "labeled" and status_state(e.ref):
            if cur:
                out.append((status_state(cur[0]) or "", cur[1], e.at))
            cur = (e.ref, e.at)
        elif e.type == "unlabeled" and cur and e.ref == cur[0]:
            out.append((status_state(cur[0]) or "", cur[1], e.at))
            cur = None
    if cur:
        out.append((status_state(cur[0]) or "", cur[1], None))
    return out


def subcontract_wait(issue: GhIssue, events: list[GhEvent], now: datetime) -> tuple[timedelta, bool]:
    """分包等了多久：从建单到交付（第一次切到配置里算「已交付」的状态，或关单）。返回 (时长, 是否已交付)；
    页面按 duration_text 写人话（不满一天写小时），卡点按天数阈值比。"""
    delivered = config.current().github.delivered
    for state, start, _end in dwell(events, now):
        if state in delivered:
            return start - issue.created_at, True
    if issue.closed_at:
        return issue.closed_at - issue.created_at, True
    return now - issue.created_at, False


@dataclass(frozen=True)
class Move:
    number: int
    title: str
    src: str
    dst: str | None     # None = 从版本里摘掉、没挂新版本
    at: datetime


def milestone_moves(gh: GhData, repo: str) -> list[Move]:
    moves: list[Move] = []
    for (r, n), evs in gh.events.items():
        if r != repo:
            continue
        title = gh.issues[(r, n)].title if (r, n) in gh.issues else ""
        cur: str | None = None
        removed: tuple[str, datetime] | None = None
        for e in evs:
            if e.type == "milestoned":
                src = cur or (removed[0] if removed else None)
                if src and src != e.ref:
                    moves.append(Move(n, title, src, e.ref, e.at))
                cur, removed = e.ref, None
            elif e.type == "demilestoned":
                if cur is None or e.ref == cur:   # 已经挂上新版本后才摘旧的，不算「摘掉」
                    removed, cur = (e.ref, e.at), None
        if cur is None and removed:
            moves.append(Move(n, title, removed[0], None, removed[1]))
    return sorted(moves, key=lambda m: m.at, reverse=True)


def related(gh: GhData, links: list[Link]) -> list[GhIssue]:
    out: list[GhIssue] = []
    for link in links:
        issue = gh.issues.get((link.repo, link.number))
        if issue:
            out.append(issue)
            out.extend(gh.children_of(link.repo, link.number))
    return out


def last_activity(gh: GhData, links: list[Link]) -> datetime | None:
    return max((i.updated_at for i in related(gh, links)), default=None)
