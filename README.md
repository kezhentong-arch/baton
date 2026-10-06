# Baton · 一棒到底

**Run your startup in owner mode: one owner per goal, many AIs, no handoffs.**

[中文说明](README.zh-CN.md) · [The essay: The Handoff Is the Bug](docs/essay.en.md) · Video: _coming soon_

Most teams still work like a relay race: one person writes the spec, hands it to the next to build, who hands it to a third to test. Every handoff drops something, and everyone waits. That trade made sense when execution was the expensive part. With AI doing most of the execution, it no longer does.

**Baton** is a way of working for small teams where everyone works with AI, plus the two boards that make it practical:

- **One rule.** Whoever starts a goal owns it to the finish: business, product, design, dev and test, with AI doing the heavy lifting. Handoffs are the exception.
- **Personal board: you and your AIs.** Every AI session files itself under a goal and a stage. You see where each thing stands, and the AI needs your yes before it moves a goal into a new stage.
- **Team board: people and people.** Who owns what, how each goal is split, how long each stage took, who is waiting on whom. Nobody fills in forms: you say it, the AI records it.

Both boards talk to your AI coding tools (Claude Code, Codex, anything that speaks MCP).

## What's in this repo

| Folder | What it is |
|---|---|
| [`personal-board/`](personal-board/) | The personal board. Python standard library only, runs on your machine, data in a local SQLite file. |
| [`team-board/`](team-board/) | The team board. Small FastAPI app. Try it locally with no login, or host it on your own server with personal tokens. |
| [`skills/`](skills/) | Skills that teach Claude Code how to work this way: when to record, when it must ask you first. |
| [`examples/`](examples/) | The real record of how these two boards were built this way (names changed), loadable into the personal board. |
| [`docs/`](docs/) | The essay: why relay-style collaboration breaks down with AI, and what replaces it. |

## Try it in two minutes

Personal board (Python 3.11+, nothing to install):

```bash
cd personal-board
./board init --name Alex --letter A     # add --lang zh for Chinese
./board seed                            # demo data: a fictional three-person team
./board start                           # http://127.0.0.1:10990
```

Team board:

```bash
cd team-board
python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
python3 -m team_board init              # add --lang zh for Chinese
python3 -m team_board seed
python3 -m team_board start             # http://127.0.0.1:10890
```

Then connect your AI (details in each folder's README):

```bash
claude mcp add -s user personal-board -- python3 /absolute/path/to/personal-board/cli/mcp.py
```

The demo data shows a made-up team building a pet-care app. It covers the situations the method is designed for: one person carrying a goal through every stage; a goal split into whole packages owned by different people; one block waiting on another; a long-running responsibility its owner breaks down by himself.

To see a real one, load the making-of record into an empty personal board:

```bash
./board seed --case ../examples/making-of.en.json --adopt-config
```

## How the pieces fit

```
you ── talk ──▶ your AI sessions ── MCP ──▶ personal board   (hourly detail, yours only)
                                               │  at wrap-up, you nod
                                               ▼
                teammates' AIs ── MCP ──▶   team board        (one summary line per goal)
```

The personal board works on its own. Connect it to a team board when there is a team.

## Privacy and hosting

Everything runs on machines you control. The personal board listens on `127.0.0.1` only. The team board refuses to listen on a public address unless token sign-in is on, and `init` generates a random token per person. There is no telemetry and no hosted service.

## Status

These boards are in daily use by the team that wrote them, and they are young. Expect rough edges; issues and pull requests are welcome.

## License

[MIT](LICENSE). Use it, change it, ship it, commercially or not; just keep the copyright notice. The license covers the code, not the name: build on Baton freely, but please don't present your own product as "Baton" or "一棒到底".
