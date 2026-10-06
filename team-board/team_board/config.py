"""配置：一个 JSON 文件，`python3 -m team_board init` 生成。

人、角色、业务线、环节、时区、语言、登录方式、GitHub 同步都在这里；代码里不认任何具体的人名、线名、环节名。
配置写错启动即拒（ConfigError），不留「配了却不生效」。

「当前配置」怎么取：每个请求由 main.py 的中间件按所属应用设好（同一进程里可以有几份配置不同的应用，测试就这么用）；
命令行、后台线程用进程级的缺省（`use()`）。只用标准库：MCP 与命令行客户端不装网页依赖也能读它。
"""
from __future__ import annotations

import contextvars
import ipaddress
import json
import os
import re
import secrets
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from team_board import i18n

ENV_CONFIG = "TEAM_BOARD_CONFIG"
DEFAULT_CONFIG_PATH = "~/.config/team-board/config.json"
DEFAULT_DATA_DIR = "~/.local/share/team-board"
DEFAULT_PORT = 10890
LANGS = ("zh", "en")
AUTH_MODES = ("local", "token")
ROLES = ("owner", "member")

# 没写颜色时按顺序取：人、线、环节各一套
PERSON_PALETTE = ("#e9c46a", "#5bc0eb", "#ef8fa9", "#9ad08f", "#c9a0f2", "#f2a65a", "#7fd1c7", "#b8bdc9")
LINE_PALETTE = ("#4fa8a0", "#7a86d6", "#b7975f", "#8a97a8", "#c77fa3", "#6fae6a", "#c98c5a", "#7d9fc9")
STAGE_PALETTE = ("#a88ef2", "#62a9f2", "#f27aa6", "#4fcb8e", "#f3ae55", "#6fd0d6", "#d9c45a", "#c58be0")
LINE_MARKS = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫"

_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
_REPO_RE = re.compile(r"^[\w.-]+/[\w.-]+$")


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Person:
    id: str
    name: str
    color: str
    letter: str          # 出生号字母：个人看板立项时发「字母＋序号」
    role: str            # owner | member
    token: str           # 个人令牌：浏览器登录、AI / 命令行的 Authorization: Bearer


@dataclass(frozen=True)
class Named:
    name: str
    color: str


@dataclass(frozen=True)
class Zone:
    name: str            # IANA 名，例如 Europe/Berlin
    label: str           # 页面上的叫法

    @cached_property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.name)


@dataclass(frozen=True)
class GitHub:
    """GitHub 只读同步（可选，默认关）：单、单的标签事件、里程碑。"""
    enabled: bool = False
    repos: tuple[tuple[str, str], ...] = ()          # (owner/name, 没有目标挂的版本归到哪条线)
    token_env: str = "TEAM_BOARD_GITHUB_TOKEN"       # 凭证从这个环境变量读，不进配置文件
    autosync: bool = False                           # 后台每 10 分钟同步一次
    since: str = "2025-01-01T00:00:00Z"              # 第一次同步从哪天起
    label_prefix: str = "stage:"                     # 只把这个前缀开头的标签当状态
    label_map: tuple[tuple[str, str], ...] = ()      # (标签的正则, 页面上写的状态)
    delivered: tuple[str, ...] = ()                  # 到了这些状态算分包已交付


@dataclass(frozen=True)
class Config:
    title: str
    lang: str
    auth: str
    host: str
    port: int
    data_dir: Path
    zone: Zone
    zone2: Zone | None
    persons: tuple[Person, ...]
    line_defs: tuple[Named, ...]
    stage_defs: tuple[Named, ...]
    github: GitHub = field(default_factory=GitHub)

    # ---- 下面都是从上面算出来的查表，页面与规则只读这些 ----
    @cached_property
    def people(self) -> dict[str, str]:
        return {p.id: p.name for p in self.persons}

    @cached_property
    def person_colors(self) -> dict[str, str]:
        return {p.id: p.color for p in self.persons}

    @cached_property
    def letters(self) -> dict[str, str]:
        return {p.id: p.letter for p in self.persons}

    @cached_property
    def owners(self) -> frozenset[str]:
        return frozenset(p.id for p in self.persons if p.role == "owner")

    @cached_property
    def by_token(self) -> dict[str, Person]:
        return {p.token: p for p in self.persons if p.token}

    @cached_property
    def lines(self) -> tuple[str, ...]:
        return tuple(x.name for x in self.line_defs)

    @cached_property
    def line_marks(self) -> dict[str, tuple[str, str]]:
        return {x.name: (LINE_MARKS[i] if i < len(LINE_MARKS) else "", x.color) for i, x in enumerate(self.line_defs)}

    @cached_property
    def stages(self) -> tuple[str, ...]:
        return tuple(x.name for x in self.stage_defs)

    @cached_property
    def stage_colors(self) -> tuple[str, ...]:
        return tuple(x.color for x in self.stage_defs)

    @cached_property
    def tz(self) -> ZoneInfo:
        return self.zone.tz

    @cached_property
    def repos(self) -> tuple[str, ...]:
        return tuple(r for r, _ in self.github.repos) if self.github.enabled else ()

    @cached_property
    def repo_line(self) -> dict[str, str]:
        return {r: ln for r, ln in self.github.repos if ln}

    @cached_property
    def source_re(self) -> str:
        """来源号（出生号）的写法：某个人的字母＋序号。"""
        return "[" + "".join(sorted(set(self.letters.values()))) + "][1-9][0-9]*"

    def person(self, pid: str) -> Person | None:
        return next((p for p in self.persons if p.id == pid), None)

    @property
    def default_person(self) -> Person:
        """本地试用模式没选「我是谁」时：第一个 owner。"""
        return next(p for p in self.persons if p.role == "owner")


# ---------------------------------------------------------------- 解析与校验

def _fail(lang: str, key: str, /, **kw) -> ConfigError:
    return ConfigError(i18n.tr(lang, key, **kw))


def _zone(raw, lang: str, key: str) -> Zone | None:
    if raw in (None, "", {}):
        return None
    if isinstance(raw, str):
        raw = {"name": raw}
    if not isinstance(raw, dict) or not isinstance(raw.get("name"), str):
        raise _fail(lang, "cfg.zone_shape", key=key)
    try:
        ZoneInfo(raw["name"])
    except (ZoneInfoNotFoundError, ValueError):
        raise _fail(lang, "cfg.zone_unknown", key=key, name=raw["name"]) from None
    label = str(raw.get("label") or "").strip() or raw["name"].split("/")[-1].replace("_", " ")
    return Zone(raw["name"], label)


def _named(items, lang: str, key: str, palette: tuple[str, ...]) -> tuple[Named, ...]:
    if not isinstance(items, list) or not items:
        raise _fail(lang, "cfg.list_empty", key=key)
    out: list[Named] = []
    for i, it in enumerate(items):
        if isinstance(it, str):
            it = {"name": it}
        name = str((it or {}).get("name") or "").strip() if isinstance(it, dict) else ""
        if not name:
            raise _fail(lang, "cfg.name_missing", key=key, n=i + 1)
        color = str(it.get("color") or palette[i % len(palette)])
        if not _COLOR_RE.match(color):
            raise _fail(lang, "cfg.color_bad", key=f"{key}[{i + 1}]", color=color)
        if name in {x.name for x in out}:
            raise _fail(lang, "cfg.duplicate", key=key, value=name)
        out.append(Named(name, color))
    return tuple(out)


def _people(items, lang: str) -> tuple[Person, ...]:
    if not isinstance(items, list) or not items:
        raise _fail(lang, "cfg.list_empty", key="people")
    out: list[Person] = []
    for i, it in enumerate(items):
        if not isinstance(it, dict):
            raise _fail(lang, "cfg.name_missing", key="people", n=i + 1)
        pid, name = str(it.get("id") or "").strip(), str(it.get("name") or "").strip()
        if not _ID_RE.match(pid):
            raise _fail(lang, "cfg.person_id", id=pid or "?")
        if not name:
            raise _fail(lang, "cfg.name_missing", key="people", n=i + 1)
        letter = str(it.get("letter") or "").strip().upper()
        if not re.fullmatch(r"[A-FH-Z]", letter):         # G 留给看板自己的目标编号
            raise _fail(lang, "cfg.letter", id=pid, letter=letter or "?")
        role = str(it.get("role") or "member")
        if role not in ROLES:
            raise _fail(lang, "cfg.role", id=pid, role=role)
        color = str(it.get("color") or PERSON_PALETTE[i % len(PERSON_PALETTE)])
        if not _COLOR_RE.match(color):
            raise _fail(lang, "cfg.color_bad", key=f"people.{pid}", color=color)
        token = str(it.get("token") or "").strip()
        for attr, value in (("id", pid), ("name", name), ("letter", letter)):
            if value in {getattr(x, attr) for x in out}:
                raise _fail(lang, "cfg.duplicate", key=f"people.{attr}", value=value)
        if token and token in {x.token for x in out}:
            raise _fail(lang, "cfg.duplicate", key="people.token", value=pid)
        out.append(Person(pid, name, color, letter, role, token))
    if not any(p.role == "owner" for p in out):
        raise _fail(lang, "cfg.no_owner")
    return tuple(out)


def _github(raw, lang: str, lines: tuple[str, ...]) -> GitHub:
    if raw in (None, {}):
        return GitHub()
    if not isinstance(raw, dict):
        raise _fail(lang, "cfg.github_shape")
    repos: list[tuple[str, str]] = []
    for it in raw.get("repos") or []:
        if isinstance(it, str):
            it = {"repo": it}
        repo, line = str(it.get("repo") or ""), str(it.get("line") or "")
        if not _REPO_RE.match(repo):
            raise _fail(lang, "cfg.repo_bad", repo=repo or "?")
        if line and line not in lines:
            raise _fail(lang, "cfg.repo_line", repo=repo, line=line)
        repos.append((repo, line))
    rules: list[tuple[str, str]] = []
    for it in raw.get("label_map") or []:
        pattern, state = str((it or {}).get("pattern") or ""), str((it or {}).get("state") or "")
        try:
            re.compile(pattern)
        except re.error:
            raise _fail(lang, "cfg.label_pattern", pattern=pattern) from None
        if not pattern or not state:
            raise _fail(lang, "cfg.label_pattern", pattern=pattern or "?")
        rules.append((pattern, state))
    enabled = bool(raw.get("enabled", False))
    if enabled and not repos:
        raise _fail(lang, "cfg.github_no_repo")
    return GitHub(enabled=enabled, repos=tuple(repos),
                  token_env=str(raw.get("token_env") or "TEAM_BOARD_GITHUB_TOKEN"),
                  autosync=bool(raw.get("autosync", False)),
                  since=str(raw.get("since") or "2025-01-01T00:00:00Z"),
                  label_prefix=str(raw.get("label_prefix") if raw.get("label_prefix") is not None else "stage:"),
                  label_map=tuple(rules), delivered=tuple(str(x) for x in raw.get("delivered") or []))


def parse_config(raw: dict) -> Config:
    if not isinstance(raw, dict):
        raise ConfigError(i18n.tr("en", "cfg.not_object"))
    lang = raw.get("lang", "zh")
    if lang not in LANGS:
        raise ConfigError(i18n.tr("en", "cfg.lang", lang=lang))
    auth = raw.get("auth", "local")
    if auth not in AUTH_MODES:
        raise _fail(lang, "cfg.auth", auth=auth)
    try:
        port = int(raw.get("port", DEFAULT_PORT))
    except (TypeError, ValueError):
        raise _fail(lang, "cfg.port", port=raw.get("port")) from None
    host = str(raw.get("host") or "127.0.0.1")
    if auth == "local" and not is_loopback(host):
        # 免登录的本地试用模式谁连上都能以任何人的身份写，所以只许本机访问
        raise _fail(lang, "cfg.unsafe_bind", host=host)
    zone = _zone(raw.get("timezone") or "UTC", lang, "timezone")
    persons = _people(raw.get("people"), lang)
    if auth == "token" and any(not p.token for p in persons):
        raise _fail(lang, "cfg.token_missing")
    line_defs = _named(raw.get("lines"), lang, "lines", LINE_PALETTE)
    stage_defs = _named(raw.get("stages"), lang, "stages", STAGE_PALETTE)
    return Config(
        title=str(raw.get("title") or i18n.tr(lang, "app.title")).strip(),
        lang=lang, auth=auth, host=host, port=port,
        data_dir=Path(str(raw.get("data_dir") or DEFAULT_DATA_DIR)).expanduser().resolve(),
        zone=zone, zone2=_zone(raw.get("second_timezone"), lang, "second_timezone"),
        persons=persons, line_defs=line_defs, stage_defs=stage_defs,
        github=_github(raw.get("github"), lang, tuple(x.name for x in line_defs)))


def is_loopback(host: str) -> bool:
    """是不是只有本机连得上的地址（127.0.0.0/8、::1、localhost）。"""
    if host.strip().lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


def config_path(explicit: str | os.PathLike | None = None) -> Path:
    return Path(str(explicit or os.environ.get(ENV_CONFIG) or DEFAULT_CONFIG_PATH)).expanduser()


def load_config(path: str | os.PathLike | None = None) -> Config:
    p = config_path(path)
    if not p.is_file():
        raise ConfigError(i18n.tr("en", "cfg.missing", path=p) + "\n" + i18n.tr("zh", "cfg.missing", path=p))
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except ValueError as e:
        raise ConfigError(i18n.tr("en", "cfg.not_json", path=p, error=e)) from None
    return parse_config(raw)


# ---------------------------------------------------------------- init 用的初始配置

def new_token() -> str:
    return "tb_" + secrets.token_urlsafe(24)


def local_zone_name() -> str:
    """本机时区的 IANA 名；认不出就 UTC（配置里随时能改）。"""
    try:
        target = os.path.realpath("/etc/localtime")
        if "zoneinfo/" in target:
            name = target.split("zoneinfo/", 1)[1]
            ZoneInfo(name)
            return name
    except (OSError, ZoneInfoNotFoundError, ValueError):
        pass
    return "UTC"


# 初始配置里的三个人是示例团队（三人初创团队，做宠物照护 App），和 `seed` 灌的示例数据对得上；换成自己的人就行
_STARTER = {
    "zh": {
        "people": [("linxia", "林夏", "L", "owner"), ("zhouxing", "周行", "Z", "member"), ("suhe", "苏禾", "S", "member")],
        "lines": ["产品", "增长", "运营", "团队协作"],
        "stages": ["业务", "产品", "UI", "开发", "测试"],
    },
    "en": {
        "people": [("alex", "Alex", "A", "owner"), ("ben", "Ben", "B", "member"), ("chloe", "Chloe", "C", "member")],
        "lines": ["Product", "Growth", "Operations", "Team"],
        "stages": ["Business", "Product", "Design", "Dev", "Test"],
    },
}


def starter_config(lang: str = "zh", *, data_dir: str = DEFAULT_DATA_DIR, port: int = DEFAULT_PORT,
                   timezone: str | None = None, timezone_label: str = "", second_timezone: str | None = None,
                   second_timezone_label: str = "", auth: str = "local", host: str = "127.0.0.1") -> dict:
    s = _STARTER[lang]
    zone = {"name": timezone or local_zone_name()}
    if timezone_label:
        zone["label"] = timezone_label
    raw: dict = {
        "title": i18n.tr(lang, "app.title"),
        "lang": lang,
        "auth": auth,
        "host": host,
        "port": port,
        "data_dir": data_dir,
        "timezone": zone,
        "second_timezone": ({"name": second_timezone, **({"label": second_timezone_label} if second_timezone_label else {})}
                            if second_timezone else None),
        "people": [{"id": pid, "name": name, "color": PERSON_PALETTE[i], "letter": letter, "role": role,
                    "token": new_token()} for i, (pid, name, letter, role) in enumerate(s["people"])],
        "lines": [{"name": n, "color": LINE_PALETTE[i]} for i, n in enumerate(s["lines"])],
        "stages": [{"name": n, "color": STAGE_PALETTE[i]} for i, n in enumerate(s["stages"])],
        "github": {
            "enabled": False,
            "repos": [{"repo": "your-org/your-repo", "line": s["lines"][0]}],
            "token_env": "TEAM_BOARD_GITHUB_TOKEN",
            "autosync": False,
            "since": "2025-01-01T00:00:00Z",
            "label_prefix": "stage:",
            "label_map": [{"pattern": "stage: todo", "state": "To do"},
                          {"pattern": "stage: dev", "state": "Dev"},
                          {"pattern": "stage: review", "state": "In review"},
                          {"pattern": "stage: done", "state": "Done"}],
            "delivered": ["In review", "Done"],
        },
    }
    parse_config(raw)      # 自己生成的也过一遍校验
    return raw


# ---------------------------------------------------------------- 当前配置

_default: Config | None = None
_current: contextvars.ContextVar[Config | None] = contextvars.ContextVar("team_board_config", default=None)


def use(cfg: Config) -> Config:
    """设为进程级缺省（命令行、后台线程、测试里直接调规则函数时用）。"""
    global _default
    _default = cfg
    i18n.set_default(cfg.lang)
    return cfg


def activate(cfg: Config):
    """只对当前上下文（一个请求）生效；返回的东西交给 deactivate。"""
    return _current.set(cfg), i18n.activate(cfg.lang)


def deactivate(tokens) -> None:
    _current.reset(tokens[0])
    i18n.deactivate(tokens[1])


def current() -> Config:
    cfg = _current.get() or _default
    if cfg is None:
        raise RuntimeError("team_board.config: no active config (call config.use(cfg) first)")
    return cfg
