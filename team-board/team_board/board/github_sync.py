"""从 GitHub 只读同步单、单的事件和里程碑（可选，配置 github.enabled 开启）。不往 GitHub 写任何东西。

另外管每日备份：后台循环每天把正式库备份一份，不管开没开同步。只用标准库联网（urllib），不加依赖。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import threading
import urllib.error
import urllib.request
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from team_board import config
from team_board.board.model import SYNC_INTERVAL_SECONDS, iso, parse_ts, tz, utc_now
from team_board.board.store import board_db_path, connect_board
from team_board.i18n import t

log = logging.getLogger("team_board.sync")

GRAPHQL_URL = "https://api.github.com/graphql"
# 列表接口只取单的基本信息，事件一律单张查（见 _issue_events 的说明）
PAGE_SIZE = 20
# 事件逐张查，单次 0.5–2 秒；一页 20 张并发查（第一次全量上千张的话，串行要一两个小时）
FETCH_WORKERS = 8

_TYPES = "[LABELED_EVENT,UNLABELED_EVENT,MILESTONED_EVENT,DEMILESTONED_EVENT,CLOSED_EVENT,REOPENED_EVENT]"
_FIELDS = """__typename
  ... on LabeledEvent{createdAt label{name}}
  ... on UnlabeledEvent{createdAt label{name}}
  ... on MilestonedEvent{createdAt milestoneTitle}
  ... on DemilestonedEvent{createdAt milestoneTitle}
  ... on ClosedEvent{createdAt}
  ... on ReopenedEvent{createdAt}"""

ISSUES_QUERY = """
query($owner:String!,$name:String!,$after:String,$since:DateTime!,$first:Int!){
  repository(owner:$owner,name:$name){
    milestones(first:100,states:[OPEN,CLOSED]){nodes{number title state dueOn createdAt closedAt}}
    issues(first:$first,after:$after,filterBy:{since:$since},orderBy:{field:UPDATED_AT,direction:ASC}){
      pageInfo{hasNextPage endCursor}
      nodes{
        number title url state createdAt updatedAt closedAt
        milestone{number} parent{number}
        labels(first:30){nodes{name}}
        assignees(first:10){nodes{login}}
      }
    }
  }
}"""

TIMELINE_QUERY = """
query($owner:String!,$name:String!,$number:Int!,$after:String){
  repository(owner:$owner,name:$name){
    issue(number:$number){
      timelineItems(first:100,after:$after,itemTypes:@TYPES@){totalCount pageInfo{hasNextPage endCursor} nodes{@FIELDS@}}
    }
  }
}""".replace("@TYPES@", _TYPES).replace("@FIELDS@", _FIELDS)

_EVENT_TYPE = {"LabeledEvent": "labeled", "UnlabeledEvent": "unlabeled",
               "MilestonedEvent": "milestoned", "DemilestonedEvent": "demilestoned",
               "ClosedEvent": "closed", "ReopenedEvent": "reopened"}

Post = Callable[[str, dict], dict]


def make_post(token: str) -> Post:
    def post(query: str, variables: dict) -> dict:
        req = urllib.request.Request(
            GRAPHQL_URL, data=json.dumps({"query": query, "variables": variables}).encode(), method="POST",
            headers={"Authorization": f"bearer {token}", "Content-Type": "application/json",
                     "User-Agent": "team-board-sync/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                body = json.loads(r.read())
        except urllib.error.HTTPError as e:
            raise RuntimeError(t("gh.http_error", status=e.code, body=e.read()[:200].decode("utf-8", "replace"))) from None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
            raise RuntimeError(t("gh.network_error", error=e)) from None
        if body.get("errors"):
            raise RuntimeError(t("gh.api_error", error=body["errors"][0].get("message", body["errors"])))
        return body["data"]

    return post


def resolve_token(env, cfg: config.Config | None = None) -> str | None:
    """GitHub 凭证只从环境变量读（变量名在配置 github.token_env），不进配置文件。"""
    cfg = cfg or config.current()
    tok = (env.get(cfg.github.token_env) or "").strip()
    return tok or None


@dataclass
class SyncResult:
    ok: bool = False
    issues_seen: int = 0
    warnings: list[str] = field(default_factory=list)
    error: str = ""


def _gh_time(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _event_row(repo: str, number: int, node: dict) -> tuple | None:
    kind = _EVENT_TYPE.get(node.get("__typename", ""))
    if kind is None or not node.get("createdAt"):
        return None
    if kind in ("labeled", "unlabeled"):
        ref = (node.get("label") or {}).get("name") or t("gh.deleted_label")
    elif kind in ("milestoned", "demilestoned"):
        ref = node.get("milestoneTitle") or ""
    else:
        ref = ""
    return (repo, number, kind, iso(parse_ts(node["createdAt"])), ref)


# 同一进程里同时只跑一轮同步：后台循环和「立即同步」撞上时，后来的直接返回「正在同步」
_SYNC_LOCK = threading.Lock()


def busy_text() -> str:
    return t("gh.busy")


def _fetch_timeline(post: Post, owner: str, name: str, number: int) -> tuple[list[dict], int]:
    """单张单的完整事件（自己翻页）。返回 (事件, GitHub 报的总数)。"""
    nodes: list[dict] = []
    after: str | None = None
    while True:
        tl = post(TIMELINE_QUERY, {"owner": owner, "name": name, "number": number,
                                   "after": after})["repository"]["issue"]["timelineItems"]
        nodes += tl["nodes"]
        if not tl["pageInfo"]["hasNextPage"]:
            return nodes, tl["totalCount"]
        after = tl["pageInfo"]["endCursor"]


def _gap(nodes: list[dict], total: int, has_labels: bool) -> str | None:
    if len(nodes) < total:
        return t("gh.gap_count", got=len(nodes), total=total)
    if not nodes and has_labels:
        return t("gh.gap_labels")
    return None


def _issue_events(post: Post, owner: str, name: str, number: int,
                 has_labels: bool) -> tuple[list[dict], int, str | None]:
    """一张单的完整事件，一律单张查。

    列表接口里顺带取事件不可信（实测）：同一页单子，一页取 5 张时某张单有 19 条事件，
    取 8 张就只给 7 条、取 20 张时另一张给 0 条——连 totalCount 也跟着变小，核对总数也发现不了。
    单张查询拿到的才是真值。抓取出错不让整轮失败：返回原因，记进 gh_incomplete 下一轮重试。"""
    try:
        nodes, total = _fetch_timeline(post, owner, name, number)
    except Exception as e:  # noqa: BLE001
        return [], 0, t("gh.fetch_failed", error=e)[:200]
    return nodes, total, _gap(nodes, total, has_labels)


def _store_milestone(conn: sqlite3.Connection, repo: str, m: dict) -> None:
    conn.execute(
        "INSERT INTO gh_milestones(repo,number,title,state,due_on,created_at,closed_at)"
        " VALUES(?,?,?,?,?,?,?) ON CONFLICT(repo,number) DO UPDATE SET title=excluded.title,"
        " state=excluded.state, due_on=excluded.due_on, closed_at=excluded.closed_at",
        (repo, m["number"], m["title"], m["state"],
         iso(parse_ts(m["dueOn"])) if m.get("dueOn") else None, iso(parse_ts(m["createdAt"])),
         iso(parse_ts(m["closedAt"])) if m.get("closedAt") else None))


def _store_issue(conn: sqlite3.Connection, repo: str, n: dict, total: int) -> None:
    conn.execute(
        "INSERT INTO gh_issues(repo,number,title,url,state,created_at,updated_at,closed_at,"
        "milestone_number,parent_number,labels,assignees,timeline_total)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)"
        " ON CONFLICT(repo,number) DO UPDATE SET title=excluded.title, url=excluded.url,"
        " state=excluded.state, updated_at=excluded.updated_at, closed_at=excluded.closed_at,"
        " milestone_number=excluded.milestone_number, parent_number=excluded.parent_number,"
        " labels=excluded.labels, assignees=excluded.assignees, timeline_total=excluded.timeline_total",
        (repo, n["number"], n["title"], n["url"], n["state"], iso(parse_ts(n["createdAt"])),
         iso(parse_ts(n["updatedAt"])), iso(parse_ts(n["closedAt"])) if n.get("closedAt") else None,
         (n.get("milestone") or {}).get("number"), (n.get("parent") or {}).get("number"),
         json.dumps([x["name"] for x in n["labels"]["nodes"]], ensure_ascii=False),
         json.dumps([x["login"] for x in n["assignees"]["nodes"]]), total))


def _store_events(conn: sqlite3.Connection, repo: str, number: int, nodes: list[dict]) -> None:
    conn.executemany(
        "INSERT OR IGNORE INTO gh_events(repo,number,type,at,ref) VALUES(?,?,?,?,?)",
        [r for r in (_event_row(repo, number, x) for x in nodes) if r])


def _mark(conn: sqlite3.Connection, repo: str, number: int, reason: str | None, now: datetime) -> None:
    if reason:
        conn.execute("INSERT INTO gh_incomplete(repo,number,reason,first_seen,last_tried)"
                     " VALUES(?,?,?,?,?) ON CONFLICT(repo,number) DO UPDATE SET"
                     " reason=excluded.reason, last_tried=excluded.last_tried",
                     (repo, number, reason, iso(now), iso(now)))
    else:
        conn.execute("DELETE FROM gh_incomplete WHERE repo=? AND number=?", (repo, number))


def incomplete(conn: sqlite3.Connection) -> list[str]:
    return [t("gh.incomplete_item", repo=r["repo"], number=r["number"], reason=r["reason"]) for r in
            conn.execute("SELECT * FROM gh_incomplete ORDER BY repo, number")]


def run_sync(conn: sqlite3.Connection, post: Post, *, repos: tuple[str, ...] | None = None,
             default_since: str | None = None, now: datetime | None = None) -> SyncResult:
    cfg = config.current()
    if not _SYNC_LOCK.acquire(blocking=False):
        return SyncResult(ok=False, error=busy_text())
    try:
        return _run_sync(conn, post, cfg.repos if repos is None else repos,
                         default_since or cfg.github.since, now or utc_now())
    finally:
        _SYNC_LOCK.release()


def _run_sync(conn: sqlite3.Connection, post: Post, repos: tuple[str, ...], default_since: str,
              now: datetime) -> SyncResult:
    res = SyncResult()
    run_id = None
    handled: set[tuple[str, int]] = set()      # 本轮已经抓过的单，收尾重试时跳过
    try:
        run_id = conn.execute("INSERT INTO gh_sync_runs(started_at) VALUES(?)", (iso(now),)).lastrowid
        conn.commit()
        for repo in repos:
            owner, name = repo.split("/")
            row = conn.execute("SELECT since FROM gh_cursor WHERE repo=?", (repo,)).fetchone()
            since = row["since"] if row else default_since
            after: str | None = None
            newest: datetime | None = None
            while True:
                # 先把这一页（含单张重抓）全部从网络拉完，再开短事务写库——联网期间不占写锁
                data = post(ISSUES_QUERY, {"owner": owner, "name": name, "after": after,
                                           "since": since, "first": PAGE_SIZE})["repository"]
                nodes_ = data["issues"]["nodes"]
                with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as pool:
                    got = list(pool.map(lambda n: _issue_events(post, owner, name, n["number"],
                                                                bool(n["labels"]["nodes"])), nodes_))
                fetched = [(n, *g) for n, g in zip(nodes_, got)]
                for m in data["milestones"]["nodes"]:
                    _store_milestone(conn, repo, m)
                for n, nodes, total, reason in fetched:
                    _store_issue(conn, repo, n, total)
                    _store_events(conn, repo, n["number"], nodes)
                    _mark(conn, repo, n["number"], reason, now)
                    handled.add((repo, n["number"]))
                    res.issues_seen += 1
                    updated = parse_ts(n["updatedAt"])
                    newest = updated if newest is None or updated > newest else newest
                conn.commit()
                page = data["issues"]["pageInfo"]
                if not page["hasNextPage"]:
                    break
                after = page["endCursor"]
            if newest is not None:
                conn.execute("INSERT INTO gh_cursor(repo,since) VALUES(?,?) ON CONFLICT(repo)"
                             " DO UPDATE SET since=excluded.since",
                             (repo, _gh_time(newest - timedelta(minutes=2))))
                conn.commit()
        # 以前没补齐的单不随游标前移而丢：每轮都单独重抓一次
        retry = [(r["repo"], r["number"], r["labels"]) for r in conn.execute(
            "SELECT i.repo, i.number, g.labels FROM gh_incomplete i"
            " LEFT JOIN gh_issues g ON g.repo=i.repo AND g.number=i.number")]
        retry = [x for x in retry if x[0] in repos and (x[0], x[1]) not in handled]

        def refetch(item):
            repo, number, labels = item
            owner, name = repo.split("/")
            return _issue_events(post, owner, name, number, bool(json.loads(labels or "[]")))

        with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as pool:
            got = list(pool.map(refetch, retry))
        for (repo, number, _labels), (nodes, _total, reason) in zip(retry, got):
            _store_events(conn, repo, number, nodes)
            _mark(conn, repo, number, reason, now)
        conn.commit()
        res.warnings = incomplete(conn)
        res.ok = True
    except Exception as e:  # noqa: BLE001 — 失败要落库并显示在页面上，下一轮重试
        conn.rollback()
        res.error = str(e)
        log.exception("[board] GitHub sync failed")
    if run_id is not None:
        try:
            conn.execute("UPDATE gh_sync_runs SET finished_at=?, ok=?, issues_seen=?, error=?,"
                         " warnings=? WHERE id=?",
                         (iso(utc_now()), int(res.ok), res.issues_seen, res.error,
                          json.dumps(res.warnings, ensure_ascii=False), run_id))
            conn.commit()
        except sqlite3.Error:
            log.exception("[board] could not record the sync run")
    return res


def start_background_sync(data_dir: Path, post: Post) -> bool:
    """「立即同步」用：在后台线程跑一轮，马上返回。第一次全量要十几分钟，
    同步等在请求里会被反向代理或命令行的超时掐断。已有一轮在跑就返回 False。"""
    if _SYNC_LOCK.locked():
        return False
    cfg = config.current()

    def work() -> None:
        tokens = config.activate(cfg)      # 新线程不带请求的上下文，把配置显式带过来
        conn = connect_board(data_dir)
        try:
            run_sync(conn, post)
        finally:
            conn.close()
            config.deactivate(tokens)

    threading.Thread(target=work, name="board-sync", daemon=True).start()
    return True


def running_since(conn: sqlite3.Connection) -> datetime | None:
    """正在进行的那一轮从什么时候开始（没有就 None）。"""
    if not _SYNC_LOCK.locked():
        return None
    r = conn.execute("SELECT started_at FROM gh_sync_runs WHERE finished_at IS NULL"
                     " ORDER BY id DESC LIMIT 1").fetchone()
    return parse_ts(r["started_at"]) if r else None


def last_success(conn: sqlite3.Connection) -> datetime | None:
    r = conn.execute("SELECT finished_at FROM gh_sync_runs WHERE ok=1 ORDER BY id DESC LIMIT 1").fetchone()
    return parse_ts(r["finished_at"]) if r else None


def latest_run(conn: sqlite3.Connection) -> sqlite3.Row | None:
    """最近一轮**已经结束**的同步（正在跑的那轮不遮住上一轮的错误）。"""
    return conn.execute("SELECT * FROM gh_sync_runs WHERE finished_at IS NOT NULL"
                        " ORDER BY id DESC LIMIT 1").fetchone()


def backup_daily(conn: sqlite3.Connection, data_dir: Path, now: datetime | None = None,
                 keep: int = 14) -> Path | None:
    """主时区每个日期备份一份看板库，保留最近 keep 份。当天已备份过就跳过。"""
    now = now or utc_now()
    folder = board_db_path(data_dir).parent / "backups"
    folder.mkdir(exist_ok=True)
    target = folder / f"board-{now.astimezone(tz()):%Y%m%d}.sqlite"
    if target.exists():
        return None
    dst = sqlite3.connect(target)
    try:
        conn.backup(dst)
    finally:
        dst.close()
    for old in sorted(folder.glob("board-*.sqlite"))[:-keep]:
        old.unlink()
    return target


def _once(cfg: config.Config, post: Post | None) -> None:
    tokens = config.activate(cfg)
    conn = connect_board(cfg.data_dir)
    try:
        if post is not None:
            run_sync(conn, post)
        backup_daily(conn, cfg.data_dir)
    finally:
        conn.close()
        config.deactivate(tokens)


async def background_loop(cfg: config.Config) -> None:
    """服务常驻时：每 10 分钟一轮——开了自动同步就同步 GitHub，另外每天备份一次正式库。"""
    post = None
    if cfg.github.enabled and cfg.github.autosync:
        token = resolve_token(os.environ, cfg)
        if token:
            post = make_post(token)
        else:
            log.warning("[board] github.autosync is on but %s is not set; background sync is off", cfg.github.token_env)
    while True:
        try:
            await asyncio.to_thread(_once, cfg, post)
        except Exception:  # noqa: BLE001 — 单轮失败记日志，不让循环死掉
            log.exception("[board] background round failed")
        await asyncio.sleep(SYNC_INTERVAL_SECONDS)
