# 一棒到底 · 个人看板

[English](README.md)

一个人，一天十几个 AI 对话。每个对话（Claude Code、Codex）通过 MCP 把自己归到**一条线、一个目标、一个环节**，做出结果就记一条；网页上一条时间线，看每件事到哪了。如果你还有团队看板，攒着的改动在收尾时由 AI 推上去——你点头之后。

- 本地优先：纯 Python 标准库，一个 sqlite 文件，一个只听 `127.0.0.1` 的网页。不用账号，不上云。
- 只追加：什么都不删；记错的作废、留痕。
- 都是配置：你是谁、有哪些线、哪些环节、哪个时区、什么语言，一个 JSON 文件说了算。
- 中英双语界面（`lang: "zh" | "en"`），MCP 工具说明和 AI 手册也跟着换。

需要 **Python 3.11+**，macOS 或 Linux（Windows 另装 `pip install tzdata`）。没有别的依赖。

## 30 秒跑起来

```bash
cd personal-board
./board init --lang zh --name 林夏 --letter L   # 生成配置、建库
./board seed                                    # 可选：灌一份虚构的演示数据先看看
./board start                                   # http://127.0.0.1:10990/
./board open
```

`./board` 是个很小的 Python 入口，和 `python3 cli/board.py …` 是一回事。演示数据是一家虚构的宠物照护创业团队负责人的看板，日期按灌入当天往前推。看够了：`./board reset --execute`，先备份、再给你一块空看板。

数据在 `~/.local/share/personal-board/`（环境变量 `PERSONAL_BOARD_DATA` 可改），不进仓库；就算把数据目录指到仓库里，`.gitignore` 也会挡住。

## 把 AI 接上

Claude Code（用户级注册，所有目录都能用）：

```bash
claude mcp add -s user personal-board -- python3 /绝对路径/personal-board/cli/mcp.py
```

Codex：在 `~/.codex/config.toml` 加一段：

```toml
[mcp_servers.personal-board]
command = "python3"
args = ["/绝对路径/personal-board/cli/mcp.py"]
```

自检：`./board mcp --check`。服务把手册（`app/guide.zh.md` / `app/guide.en.md`）作为 MCP 说明带给 AI：对话一开始先归类、出了结果记一条、进新环节先问、收尾。工具：`personal_board_state`、`_goal`、`_timeline`、`_pending`、`_actions`、`_guide`、`_time`、`_act`、`_pull`。MCP 直接开数据库，网页没起也能记。

Claude Code 可选的开场提醒，写进 `~/.claude/settings.json` 的 `hooks.SessionStart`：

```json
{"hooks": [{"type": "command", "command": "echo '对话开始：按个人看板手册先把这个对话归到线 / 目标 / 环节，说一句并记开工（闲聊问答不记）。'"}]}
```

## 命令

| 命令 | 做什么 |
|---|---|
| `./board init [--lang zh\|en] [--name 名字] [--letter 字母] [--timezone 时区] [--second-timezone 时区] [--port 端口]` | 生成 `config.json`、建库。`--force` 重写已有配置。 |
| `./board seed [--lang zh\|en]` | 往**空库**里灌演示数据。 |
| `./board seed --case 文件 [--adopt-config]` | 往空库里灌一份样例包（别人导出的看板）。 |
| `./board export-case 文件` | 把自己的看板导出成样例包。 |
| `./board start \| stop \| status \| open` | 本地服务。`serve` 是前台跑。 |
| `./board pull` | 从团队看板拉自己负责的目标（配了才有）。 |
| `./board practice --execute` | 重建练手库。 |
| `./board reset --execute` | 先备份，再清空正式看板。 |
| `./board backup --execute` | 在线备份，保留最近 30 份。 |
| `./board app --execute` | macOS：在 `~/Applications` 装一个双击入口。 |
| `./board mcp [--check] [--practice]` | MCP 服务（stdio）。 |

一个进程出三份数据：`/` 正式；`/sample/` 示例，正式数据的实时镜像加两个假设案例，只读；`/practice/` 练手，随便操作、可重置（AI 要连它设 `PERSONAL_BOARD_PRACTICE=1`）。

## 配置

数据目录里的 `config.json`，样子见 [`config.example.json`](config.example.json)。改完重启服务。

| 键 | 含义 |
|---|---|
| `lang` | `"zh"` 或 `"en"`：全部界面文字、操作说明、AI 手册。 |
| `person` | `id`、显示名 `name`、出生号字母 `letter`（一个大写字母，不能是 `G`、`E`）。你立的每个目标拿到「字母＋序号」（`L19`），一辈子不变、不重发。 |
| `lines` | 你的线：`name`、`color`；私事那条带 `personal: true`——不拆环节、永远不推团队看板。行为只认这个标记，不认名字。 |
| `stages` | 环节的名称和颜色（默认：业务、产品、UI、开发、测试）。 |
| `timezone` | 主时区：IANA 名 `name` + 显示用的 `label`。分日、钟点、计划日都按它。 |
| `second_timezone` | 可选。配了，请人确认时刻的地方两地都写，点状任务可以按任一边的钟点；不配，所有地方只写一地。 |
| `port` | 本地端口（默认 10990）。服务只监听 `127.0.0.1`。 |
| `team_board` | `base_url` + `token`。**留空就是关闭**：不拉、不标「未推」、页面上没有任何相关提示。 |

改线名、环节名不会改库里已经存下的名字；配置里没有了的线，它的目标排在最后。

## 连团队看板（可选）

```json
"team_board": {"base_url": "https://board.example.com", "token": "…"}
```

令牌也可以放环境变量 `PERSONAL_BOARD_TEAM_TOKEN`。配上以后：

- **拉**（页面开着时每 10 分钟一次，或 `./board pull`）：`GET {base_url}/api/board/state`，带 `Authorization: Bearer <token>`。`owner` 是你（你的 `name` 或 `id`，或 `team_board.owner`）的目标连同它们的上层会镜像过来，团队看板上发生的事在这边补成记录。
- **推**：团队线上的立项、环节起止、改期、完成会标「未推」。收尾时 AI 列出来、你点头，它经团队看板自己的 MCP 推上去，再标成已推。个人看板自己从不写团队看板。
- 线或环节在团队看板上叫法不同，在配置里那一项加 `"team_name": "…"`。

可以配本仓库同级的 [`team-board`](../team-board/)，也可以配任何提供同一个接口的服务。

## 样例包

`./board export-case 林夏.json` 把你的目标、记录、待办（不含口述）写成一个 JSON 文件。在另一台电脑上 `./board seed --case 林夏.json` 灌进空库，当一份照着看的案例：不往任何地方推，未推的一律变成「不推」，`reset` 之前不拉团队目标。加 `--adopt-config` 会把样例包的线和环节写进你的配置，显示得和原来一样。

## 目录

```
board               入口（./board <命令>）
cli/board.py        各个命令          cli/mcp.py      MCP 服务（stdio）     cli/backup.py   在线备份
app/settings.py     配置              app/i18n.py     翻译表（strings_zh.py / strings_en.py）
app/actions.py      全部写操作与规则（AI 追问缺什么就看它的操作说明）
app/view.py         读模型：当天、时间线（行由窗口决定）、目标详情、未推清单
app/points.py       点状任务          app/team.py     拉团队看板           app/case.py    样例包
app/seed.py         演示数据、重置    app/sample.py   示例镜像与练手库
app/server.py       http.server：页面 + /api/*        app/templates/、app/static/
app/guide.zh.md、app/guide.en.md      带给 AI 的手册
tests/              pytest
```

## 测试

```bash
python3 -m pip install pytest && python3 -m pytest tests -q
# 或者用 uv：uv run --no-project --with pytest python -m pytest tests -q
```

测试只用临时数据目录，不碰你的看板。
