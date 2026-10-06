# 一棒到底 · 团队看板

[English](README.md)

一个小团队的目标时间线：每个目标谁负责、拆成了哪些块（G17 → G17.1 → G17.1.2）、每个环节（业务、产品、UI、开发、测试）花了多久、卡在哪、延期多少。

人不填表。你用自己的话把事情说清楚，AI 经 MCP 把它变成看板上的记录，规则由看板把关。

- FastAPI + Jinja2 + SQLite。事件只追加、状态现算——延期没法被悄悄改没。
- 人、角色、业务线、环节、时区、语言（中文 / English）都在一个 JSON 配置文件里。
- 不依赖任何云服务：在自己电脑上跑，或者放到自己的服务器上、前面加一层反向代理。

## 30 秒跑起来

要 Python 3.11 或更新。

```bash
cd team-board
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt

python3 -m team_board init --lang zh     # 生成 ~/.config/team-board/config.json，每人一个随机令牌
python3 -m team_board seed               # 可选：灌一份虚构的三人团队示例看板
python3 -m team_board start              # http://127.0.0.1:10890
```

`init` 生成的是一支示例团队（林夏、周行、苏禾）。把人、线、环节换成自己的：直接改那个 JSON 文件，然后重启。配置想放别处，给任何命令加 `--config 路径`，或设环境变量 `TEAM_BOARD_CONFIG`。

示例数据是一家虚构的宠物照护创业公司「爪印」。六个目标各演示一种协作情形：

| 目标 | 演示什么 |
|---|---|
| G1 会员订阅上线 | 发起人只做业务环节，执行拆成几个整包，其中一块跨到别的线。上游改期后晚于下游需要它的日子，看板提前亮出「依赖冲突」；下游做到一半「等依赖」暂停。 |
| G2 新用户引导改版 | 一个人从业务做到测试，环节重叠、回头再进同一环节。带个人看板推上来的来源号。 |
| G3 宠物医院合作落地页 | 已完成，有「做什么」「做了什么」。 |
| G4 崩溃率降到 0.5% 以下 | 长期负责、没有完成日；负责人自己在下面拆带日期的块给自己，其中一块改过计划日、已延期。 |
| G5 新协作方式落地 | 笼统的事，不拆环节，只看起止。 |
| G6 智能喂养提醒 1.0 | 一个目标拆三块：一块整包给别人、一块不用等谁、一块的开发要等另一块（暂停，对方完成后恢复）。整体拖过了计划日。 |

## 接上你的 AI（MCP）

MCP 服务只是看板 HTTP 接口的薄包装，只用标准库。用 `tb.py` 启动，从哪个目录跑都行：

```bash
# Claude Code
claude mcp add team-board \
  -e TEAM_BOARD_URL=http://127.0.0.1:10890 \
  -e TEAM_BOARD_TOKEN=<你的个人令牌> \
  -- python3 /绝对路径/team-board/tb.py mcp
```

```toml
# Codex：~/.codex/config.toml
[mcp_servers.team-board]
command = "python3"
args = ["/绝对路径/team-board/tb.py", "mcp"]
env = { TEAM_BOARD_URL = "http://127.0.0.1:10890", TEAM_BOARD_TOKEN = "<你的个人令牌>" }
```

令牌在配置文件里（`python3 -m team_board people` 能列出来）。**令牌决定你是谁**：AI 写下的每条记录都算令牌主人的。本地试用模式可以不带令牌，这时 AI 以第一位团队负责人的身份操作。

自检：`TEAM_BOARD_URL=… TEAM_BOARD_TOKEN=… python3 tb.py mcp --check`。

工具：`board_actions`（规则与取值表）、`board_guide`（录入手册全文）、`board_state`、`board_note`、`board_time`、`board_act`（会写）、`board_resolve_note`（会写）。手册随包自带（`team_board/guide.zh.md`、`guide.en.md`），按 `lang` 下发。

平时怎么用：在看板的「口述录入」框里打字或语音输入，点「保存并复制给 AI」，粘到 AI 对话框。AI 读口述、缺什么先问、把操作清单给你确认、确认后写入、写完回读、把口述标记为已录入。

### 用终端

```bash
python3 tb.py act state --as linxia                                 # 只读
python3 tb.py act start_stage --as zhouxing --param goal_id=7 --param stage=开发 --execute
python3 tb.py find G27                                              # 这个目标、相关提交、关联的 Issue
```

写操作要加 `--execute`，不加只打印将发送的内容。`find` 会找出提交信息里有一行 `Board-Goal: <永久号或来源号>` 的提交。

## 配置项

一个 JSON 文件。样子见 [`config.example.json`](config.example.json)（里面全是占位值；真的随机令牌由 `init` 生成）。

| 键 | 含义 |
|---|---|
| `title` | 页头和网页标题上的名字。默认「团队看板」。 |
| `lang` | `"zh"` 或 `"en"`：界面文字、报错、MCP 工具说明、手册都跟着变。 |
| `auth` | `"local"`（默认：免登录，页面上选「我是谁」，只许本机访问）或 `"token"`（个人令牌）。 |
| `host`、`port` | 监听地址。默认 `127.0.0.1:10890`。免登录模式只能监听本机回环地址。 |
| `data_dir` | SQLite 文件和备份放哪。默认 `~/.local/share/team-board`。 |
| `timezone` | 主时区：`{"name": "<IANA 时区名>", "label": "<页面上的叫法>"}`。计划完成日、按天切分都按它。 |
| `second_timezone` | 可选。配了，请人确认时刻时两地都写；设为 `null`，所有地方只写一地。 |
| `people[]` | `id`、`name`、`color`、`letter`（出生号字母，一个大写字母，G 除外）、`role`（`"owner"` 或 `"member"`）、`token`。 |
| `lines[]` | 业务线：`name`、`color`。 |
| `stages[]` | 环节：`name`、`color`。默认业务、产品、UI、开发、测试。 |
| `github` | 可选的只读同步，默认关。见下。 |

**角色。** 团队负责人（`owner`，可以有多个）能新开顶层目标、把事拆给别人、换负责人、放弃、改挂和换线。每个人都能录自己负责的目标、在自己的目标下面拆子目标给自己、替别人做环节时记自己那一段的起止。

**GitHub 同步（可选）。** 把 `github.enabled` 设为 `true`，在 `repos` 里写仓库（每个带上 `line`：没有目标挂的里程碑归哪条线），再把凭证放进 `token_env` 指的环境变量（默认 `TEAM_BOARD_GITHUB_TOKEN`）。看板只读不写：里程碑成为「版本」，关联的单能看到在每个状态停了多久。`label_map` 把标签映射成状态名，例如 `stage: dev` → `Dev`。不开它，看板也是完整可用的。

环境变量：`TEAM_BOARD_CONFIG`（配置路径）、`TEAM_BOARD_URL`、`TEAM_BOARD_TOKEN`、`TEAM_BOARD_LANG`（客户端一侧）、`TEAM_BOARD_GITHUB_TOKEN`。

## 三份数据

| | 地址 | 是什么 |
|---|---|---|
| 正式 | `/board` | `board.sqlite`，团队真实的记录。 |
| 练手 | `/board/practice` | `practice.sqlite`，正式看板的一份副本。随便操作，一键重置。AI 调工具时带 `practice=true` 就落在这里。`python3 -m team_board seed --practice` 可以改成往里灌示例数据。 |
| 示例 | `/board/sample` | 正式看板再加上用 `sample=1` 立的目标：拿假设的案例讨论看板怎么用。它们不会出现在正式看板上。 |

## 放到服务器上给团队用

1. 用令牌模式生成配置：`python3 -m team_board init --auth token`（只有在容器里才用 `--host 0.0.0.0`）。把每个人的令牌私下发给本人。
2. 程序留在 `127.0.0.1`，前面放一个带 HTTPS 的反向代理。[`deploy/Caddyfile.example`](deploy/Caddyfile.example) 是一份针对 `board.example.com` 的完整示例。
3. 作为服务常驻：[`deploy/team-board.service.example`](deploy/team-board.service.example)（systemd），或者用 Docker：

```bash
mkdir -p config
python3 -m team_board init --auth token --host 0.0.0.0 --data-dir /data --config config/config.json
chmod 644 config/config.json      # 容器里的用户要读得到；这个文件夹本身别给别人看
docker compose up -d              # 监听 127.0.0.1:10890；数据在 board-data 卷里
```

之后每个人用 `TEAM_BOARD_URL=https://board.example.com` 和自己的令牌注册 MCP。

安全上的默认值：

- 免登录的本地试用模式只监听本机回环地址。要监听别的地址必须是令牌模式，否则拒绝启动并说明原因。
- 令牌是随机的（`init` 生成），没有默认令牌、默认密码。配置文件写出来就是只有自己能读（600）。
- 登录 cookie 带 `HttpOnly`、`SameSite=Lax`；请求是 HTTPS 来的（直连或代理转来的 `X-Forwarded-Proto`）时再加 `Secure`。
- 客户端不会把令牌用明文 `http://` 发到本机以外的地址。
- 配置文件和数据库不要进版本库（`.gitignore` 已经挡住）。

## 备份与恢复

```bash
python3 -m team_board backup                    # 在线备份 → <data_dir>/board/backups/board-年月日-时分秒.sqlite
python3 -m team_board backup --out /某个目录
```

用的是 SQLite 的在线备份，服务不用停。服务常驻时还会每天自动备份一份（留最近 14 份），放在同一个文件夹。用 Docker 时：`docker compose exec board python -m team_board backup`。

恢复：停服务，把备份文件拷成 `<data_dir>/board/board.sqlite`（旁边若有 `board.sqlite-wal`、`board.sqlite-shm` 一并删掉），再启动。

## 让别的工具读看板

页面上看得到的东西都有 JSON 接口，带 `Authorization: Bearer <个人令牌>`：

- `GET /api/board/state`：全部目标和各个时刻（立项、每段环节的起止、暂停、改期、完成）、卡点、口述清单、`me`。
- `GET /api/board/actions`：操作说明与取值表。
- `GET /api/board/resolve?num=G2.5`：任意一种目标号对到目标。
- `POST /api/board/act`：`{"action": "...", "params": {...}}`。

练手看板是同一套接口，路径换成 `/api/board/practice/…`。

## 测试

```bash
pip install -r requirements-dev.txt
python3 -m pytest -q
```

## 目录

```
team_board/
  config.py        JSON 配置：人、角色、线、环节、时区
  i18n.py          一张翻译表，中英并排
  auth.py          本地试用模式 / 令牌模式
  main.py          FastAPI 应用
  board/           事件存储、状态折叠、写操作（规则都在这）、页面数据、可选的 GitHub 同步
  templates/       页面
  seed.py          虚构的示例数据
  mcp.py           MCP 服务（只用标准库）
  guide.zh.md、guide.en.md   给 AI 的录入手册
tb.py              从任何目录跑任何命令
deploy/            systemd 与反向代理示例
```
