# Baton Team Board

[中文说明](README.zh-CN.md)

A goal timeline for a small team. For every goal it shows who owns it, how it was split into parts (G17 → G17.1 → G17.1.2), how long each stage took (business, product, design, dev, test), where it is stuck, and how late it is.

Nobody fills in forms. You say what happened in your own words, your AI turns it into records through MCP, and the board checks the rules.

- FastAPI + Jinja2 + SQLite. Events are append-only; the state is computed from them, so a slipped date can't be quietly edited away.
- People, roles, lines, stages, time zones and language (English / 中文) come from one JSON config file.
- No cloud dependency: runs on your laptop, or on your own server behind a reverse proxy.

## Run it in 30 seconds

Python 3.11 or newer.

```bash
cd team-board
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt

python3 -m team_board init --lang en     # writes ~/.config/team-board/config.json with a random token per person
python3 -m team_board seed               # optional: a fictional three-person team's demo board
python3 -m team_board start              # http://127.0.0.1:10890
```

`init` creates a starter team (Alex, Ben, Chloe). Edit the JSON file to put in your own people, lines and stages, then restart. Pass `--config PATH` to any command, or set `TEAM_BOARD_CONFIG`, to keep the config elsewhere.

The demo data is a fictional pet-care startup, "Pawprint". Each of its six goals shows one way of working together:

| Goal | What it shows |
|---|---|
| G1 Launch paid membership | The initiator does only the business stage; execution is split into whole packages, one of them on another line. A dependency is flagged early when the upstream date slips past the date it is needed; the downstream part pauses, waiting. |
| G2 New-user onboarding redesign | One person, business through test, with overlapping stages and a return to an earlier stage. Carries a source number from a personal board. |
| G3 Vet-clinic partner landing page | Done, with "What" and "What was done". |
| G4 Crash rate under 0.5% | An ongoing responsibility with no finish date; its owner splits dated parts for himself. One part was replanned and is late. |
| G5 Roll out the new way of working | A broad goal with no stages, just start and end. |
| G6 Smart feeding reminders 1.0 | One goal in three parts: one handed over whole, one that waits for nobody, one whose dev waits on another part (pause, then resume). It ran past its due date. |

## Connect your AI (MCP)

The MCP server is a thin, standard-library-only wrapper over the board's HTTP API. Use `tb.py`, which works from any directory:

```bash
# Claude Code
claude mcp add team-board \
  -e TEAM_BOARD_URL=http://127.0.0.1:10890 \
  -e TEAM_BOARD_TOKEN=<your personal token> \
  -- python3 /absolute/path/to/team-board/tb.py mcp
```

```toml
# Codex: ~/.codex/config.toml
[mcp_servers.team-board]
command = "python3"
args = ["/absolute/path/to/team-board/tb.py", "mcp"]
env = { TEAM_BOARD_URL = "http://127.0.0.1:10890", TEAM_BOARD_TOKEN = "<your personal token>" }
```

Your token is in the config file (`python3 -m team_board people` lists them). **The token decides who you are**: every record the AI writes counts as its holder's. In local mode the token may be left out, and the AI then acts as the first team owner.

Check the connection: `TEAM_BOARD_URL=… TEAM_BOARD_TOKEN=… python3 tb.py mcp --check`.

Tools: `board_actions` (the rules and allowed values), `board_guide` (the full recording guide), `board_state`, `board_note`, `board_time`, `board_act` (writes), `board_resolve_note` (writes). The guide ships inside the package (`team_board/guide.en.md`, `guide.zh.md`) and follows `lang`.

Typical use: type or dictate into the "Dictation" box on the board, click "Save & copy for AI", paste into your AI chat. The AI reads the dictation, asks for anything missing, shows you the list of actions, writes them after your OK, reads back, and marks the dictation as recorded.

### From a terminal

```bash
python3 tb.py act state --as alex                                   # read
python3 tb.py act start_stage --as ben --param goal_id=7 --param stage=Dev --execute
python3 tb.py find G27                                              # the goal, its commits and linked issues
```

Writes need `--execute`; without it the command only prints what it would send. `find` lists commits whose message contains a line `Board-Goal: <permanent or source number>`.

## Configuration

One JSON file. See [`config.example.json`](config.example.json) (placeholders only; `init` generates real random tokens).

| Key | Meaning |
|---|---|
| `title` | Name shown in the header and page titles. Default "Team Board". |
| `lang` | `"en"` or `"zh"`: all UI text, error messages, MCP tool descriptions and the guide. |
| `auth` | `"local"` (default: no login, pick who you are on the page; loopback only) or `"token"` (personal tokens). |
| `host`, `port` | Listen address. Default `127.0.0.1:10890`. Local mode refuses anything but loopback. |
| `data_dir` | Where the SQLite files and backups live. Default `~/.local/share/team-board`. |
| `timezone` | Primary time zone: `{"name": "<IANA name>", "label": "<display label>"}`. Due dates and day boundaries use it. |
| `second_timezone` | Optional. When set, times are confirmed in both zones; when `null`, only one is ever written. |
| `people[]` | `id`, `name`, `color`, `letter` (source-number letter, one uppercase letter except G), `role` (`"owner"` or `"member"`), `token`. |
| `lines[]` | Business lines: `name`, `color`. |
| `stages[]` | Stages: `name`, `color`. Default: Business, Product, Design, Dev, Test. |
| `github` | Optional read-only sync, off by default. See below. |

**Roles.** A team `owner` (there can be several) may create top-level goals, hand parts to other people, reassign, abandon, move goals and change their line. Everyone may record goals they own, split sub-goals under their own goals for themselves, and record their own span when doing a stage on someone else's goal.

**GitHub sync (optional).** Set `github.enabled` to `true`, list `repos` (each with the `line` its unattached milestones belong to), and export a token in the variable named by `token_env` (default `TEAM_BOARD_GITHUB_TOKEN`). The board then reads issues, label events and milestones (never writes): milestones become "versions", linked issues show how long they sat in each state. `label_map` maps label patterns to state names, e.g. `stage: dev` → `Dev`. The board is complete without it.

Environment variables: `TEAM_BOARD_CONFIG` (config path), `TEAM_BOARD_URL`, `TEAM_BOARD_TOKEN`, `TEAM_BOARD_LANG` (client side), `TEAM_BOARD_GITHUB_TOKEN`.

## Three sets of data

| | URL | What it is |
|---|---|---|
| Real | `/board` | `board.sqlite`. The team's actual record. |
| Practice | `/board/practice` | `practice.sqlite`, a copy of the real board. Try anything, reset in one click. The AI uses it when a tool call carries `practice=true`. `python3 -m team_board seed --practice` fills it with the demo data instead. |
| Sample | `/board/sample` | The real board plus goals created with `sample=1`: hypothetical cases for discussing how to use the board. They never appear on the real board. |

## Put it on a server for your team

1. Create the config in token mode: `python3 -m team_board init --auth token` (use `--host 0.0.0.0` only inside a container). Hand each person their own token, privately.
2. Keep the app on `127.0.0.1` and put a reverse proxy with HTTPS in front. [`deploy/Caddyfile.example`](deploy/Caddyfile.example) is a complete example for `board.example.com`.
3. Run it as a service: [`deploy/team-board.service.example`](deploy/team-board.service.example) (systemd), or Docker:

```bash
mkdir -p config
python3 -m team_board init --auth token --host 0.0.0.0 --data-dir /data --config config/config.json
chmod 644 config/config.json      # readable by the container user; keep the folder private
docker compose up -d              # listens on 127.0.0.1:10890; data in the "board-data" volume
```

Teammates then register the MCP with `TEAM_BOARD_URL=https://board.example.com` and their own token.

Security defaults:

- Local (no-login) mode only listens on loopback. Listening on any other address requires token mode; otherwise the server refuses to start and says why.
- Tokens are random (`init` generates them); there is no default token or password. The config file is written with mode 600.
- The login cookie is `HttpOnly`, `SameSite=Lax`, and `Secure` when the request arrived over HTTPS (directly or via `X-Forwarded-Proto`).
- Clients refuse to send a token over plain `http://` to anything but localhost.
- The config file and databases must stay out of version control (`.gitignore` covers them).

## Backup and restore

```bash
python3 -m team_board backup                    # online backup → <data_dir>/board/backups/board-YYYYMMDD-HHMMSS.sqlite
python3 -m team_board backup --out /some/dir
```

It uses SQLite's online backup, so the server can keep running. While the server runs it also keeps one backup per day (the last 14) in the same folder. With Docker: `docker compose exec board python -m team_board backup`.

To restore: stop the server, copy a backup over `<data_dir>/board/board.sqlite` (remove any `board.sqlite-wal` and `board.sqlite-shm` next to it), start the server.

## Reading the board from other tools

Everything the pages show is available as JSON, with `Authorization: Bearer <personal token>`:

- `GET /api/board/state` — all goals with their moments (created, each stage span, pauses, due changes, done), blockers, dictations, `me`.
- `GET /api/board/actions` — the action reference and allowed values.
- `GET /api/board/resolve?num=G2.5` — any goal number to the goal.
- `POST /api/board/act` — `{"action": "...", "params": {...}}`.

The practice board has the same endpoints under `/api/board/practice/…`.

## Tests

```bash
pip install -r requirements-dev.txt
python3 -m pytest -q
```

## Layout

```
team_board/
  config.py        the JSON config: people, roles, lines, stages, time zones
  i18n.py          one translation table, zh and en side by side
  auth.py          local mode / token mode
  main.py          the FastAPI app
  board/           events store, state folding, actions (the rules), views, optional GitHub sync
  templates/       pages
  seed.py          the fictional demo data
  mcp.py           MCP server (stdlib only)
  guide.en.md, guide.zh.md   the AI's recording guide
tb.py              run any command from any directory
deploy/            systemd and reverse-proxy examples
```
