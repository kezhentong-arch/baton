# Baton Personal Board

[中文](README.zh-CN.md)

One person, a dozen AI conversations a day. Each conversation (Claude Code, Codex) files itself under **a line, a goal and a stage** through MCP and logs what it got done; the web page shows, on one timeline, where everything on your plate stands. If you also run a team board, the changes that piled up are pushed there at wrap-up — by the AI, after you nod.

- Local first: pure Python standard library, a sqlite file, a page on `127.0.0.1`. No account, no cloud.
- Append-only: nothing is deleted; a wrong entry is voided and stays on record.
- Yours to shape: who you are, your lines, stages, time zones and language are one JSON file.
- English and Chinese interface (`lang: "en" | "zh"`), including the MCP tool descriptions and the guide the AI follows.

Requires **Python 3.11+** on macOS or Linux (on Windows also `pip install tzdata`). No other dependencies.

## 30 seconds

```bash
cd personal-board
./board init --name Alex --letter A      # writes the config, creates the database
./board seed                             # optional: a fictional demo board to look around in
./board start                            # http://127.0.0.1:10990/
./board open
```

`./board` is a small Python launcher; `python3 cli/board.py …` is the same thing. The demo is the board of the lead of a fictional pet-care startup, dated relative to today. Done looking: `./board reset --execute` backs the database up and gives you an empty board.

Data lives in `~/.local/share/personal-board/` (override with `PERSONAL_BOARD_DATA`). It never goes into the repository; `.gitignore` covers it even if you point the data directory inside the checkout.

## Connect your AI

Claude Code (user scope, available in every directory):

```bash
claude mcp add -s user personal-board -- python3 /ABS/PATH/personal-board/cli/mcp.py
```

Codex — add to `~/.codex/config.toml`:

```toml
[mcp_servers.personal-board]
command = "python3"
args = ["/ABS/PATH/personal-board/cli/mcp.py"]
```

Check it: `./board mcp --check`. The server hands the AI its guide (`app/guide.en.md` / `app/guide.zh.md`) as MCP instructions: file the conversation first, log each visible result, ask before entering a new stage, wrap up. Tools: `personal_board_state`, `_goal`, `_timeline`, `_pending`, `_actions`, `_guide`, `_time`, `_act`, `_pull`. The MCP server opens the database directly, so logging works even when the web page is not running.

Optional nudge for Claude Code, in `~/.claude/settings.json` under `hooks.SessionStart`:

```json
{"hooks": [{"type": "command", "command": "echo 'Conversation start: follow the personal-board guide — file this conversation under a line / goal / stage, say so and log the start (skip small talk).'"}]}
```

## Commands

| Command | What it does |
|---|---|
| `./board init [--lang en\|zh] [--name N] [--letter L] [--timezone Z] [--second-timezone Z] [--port P]` | Write `config.json`, create the database. `--force` rewrites an existing config. |
| `./board seed [--lang en\|zh]` | Fill the **empty** board with the demo data. |
| `./board seed --case FILE [--adopt-config]` | Fill the empty board from a case pack (someone's exported board). |
| `./board export-case FILE` | Export your board as a case pack. |
| `./board start \| stop \| status \| open` | The local server. `serve` runs it in the foreground. |
| `./board pull` | Pull your goals from the team board (when one is configured). |
| `./board practice --execute` | Rebuild the practice database. |
| `./board reset --execute` | Back up, then empty the main board. |
| `./board backup --execute` | Online backup, keeping the latest 30. |
| `./board app --execute` | macOS: a double-click launcher in `~/Applications`. |
| `./board mcp [--check] [--practice]` | The MCP server (stdio). |

One process serves three data sets: `/` your board, `/sample/` a read-only live mirror of it plus two hypothetical cases, `/practice/` a sandbox you can reset (point an AI at it with `PERSONAL_BOARD_PRACTICE=1`).

## Configuration

`config.json` in the data directory; see [`config.example.json`](config.example.json). Restart the server after editing.

| Key | Meaning |
|---|---|
| `lang` | `"en"` or `"zh"`: every piece of interface text, the action reference and the AI guide. |
| `person` | `id`, display `name`, and `letter` — one capital letter (not `G` or `E`) for your **birth numbers**: every goal you create gets letter + sequence (`A19`), which never changes and is never reused. |
| `lines` | Your lines of work: `name`, `color`, and `personal: true` on lines that are private — no push to a team board, ever. Behaviour hangs on this flag, never on a name. |
| `stages` | Stage names and colours (default: Business, Product, Design, Dev, Test). |
| `timezone` | Main time zone: IANA `name` + display `label`. Days, hours and plans follow it. |
| `second_timezone` | Optional. When set, every "confirm this moment" text is written in both zones and point tasks may follow either clock; when absent, only one zone is ever written. |
| `port` | Local port (default 10990). The server binds `127.0.0.1` only. |
| `team_board` | `base_url` + `token`. **Empty = off**: no pulls, no "unpushed" marks, nothing about it on the page. |

Names already stored in the database are not renamed when you rename a line or a stage; goals on a line that left the config are listed last.

## Connect a team board (optional)

```json
"team_board": {"base_url": "https://board.example.com", "token": "…"}
```

The token may instead come from the `PERSONAL_BOARD_TEAM_TOKEN` environment variable. Once set:

- **Pull** (every 10 minutes while the page is open, or `./board pull`): `GET {base_url}/api/board/state` with `Authorization: Bearer <token>`. Goals whose `owner` is you (your `name` or `id`, or `team_board.owner`) and their parents are mirrored; what happened to them on the team board is logged here.
- **Push**: creations, stage starts and ends, plan changes and completions on team lines are marked "unpushed". At wrap-up the AI lists them, you nod, and it pushes them through the team board's own MCP, then marks them pushed. The personal board itself never writes to the team board.
- A line or stage named differently on the team board takes `"team_name": "…"` in its config entry.

Works with the sibling [`team-board`](../team-board/) of this repository, or anything that serves the same endpoint.

## Case packs

`./board export-case alex.json` writes your goals, entries and to-dos (not your dictations) to one JSON file. On another machine, `./board seed --case alex.json` loads it into an empty board as a worked example: nothing is pushed anywhere, unpushed entries arrive as "not pushed", and team pulls stay off until `reset`. Add `--adopt-config` to take the pack's lines and stages into your config so it displays exactly as it did.

## Layout

```
board               launcher (./board <command>)
cli/board.py        commands          cli/mcp.py      MCP server (stdio)      cli/backup.py   online backup
app/settings.py     configuration     app/i18n.py     translation table (strings_en.py / strings_zh.py)
app/actions.py      every write and its rules (the action reference the AI asks from)
app/view.py         read model: the day, the timeline (rows decided by the window), goal detail, unpushed list
app/points.py       point tasks       app/team.py     team-board pull      app/case.py    case packs
app/seed.py         demo data, reset  app/sample.py   example mirror and practice database
app/server.py       http.server: pages + /api/*       app/templates/, app/static/
app/guide.en.md, app/guide.zh.md      the guide the AI receives
tests/              pytest
```

## Tests

```bash
python3 -m pip install pytest && python3 -m pytest tests -q
# or, with uv:  uv run --no-project --with pytest python -m pytest tests -q
```

The tests use temporary data directories and never touch your board.
