# Baton skills

[中文](README.zh-CN.md)

Baton is a way for small teams to work in the AI era: **whoever starts a piece of work owns it to the end.** The owner
takes a goal through Business, Product, UI Design, Dev and Test with AI; handoffs between people are the exception.

This folder holds the skill that teaches an AI coding assistant (Claude Code, Codex and the like) how to work with
such an owner.

## What is here

```
en/baton-owner/                 English
  SKILL.md                      main skill: stages, checkpoints, whole package vs. subcontracting, wrap-up
  references/
    stage-business.md           state the outcome, create the goal, split it into blocks
    stage-product-design.md     spec and prototype; the prototype is the anchor
    stage-dev.md                get it running first; not done until self-tested
    stage-test.md               list, operate for real, close Test and Dev together
zh/baton-owner/                 Chinese, same structure
```

The AI loads `SKILL.md` when the work calls for it and opens a stage reference only on entering that stage.
Pick one language; both install under the same name, `baton-owner`.

## Install

**Claude Code** — copy the folder into your personal skills, or into one project:

```bash
# for you, in every project
mkdir -p ~/.claude/skills && cp -r en/baton-owner ~/.claude/skills/

# or for everyone working in one repo
mkdir -p /path/to/repo/.claude/skills && cp -r en/baton-owner /path/to/repo/.claude/skills/
```

Start a new conversation; Claude Code picks the skill up from its `description`.

**Codex** — copy the folder anywhere in your repo (for example `docs/skills/baton-owner/`) and point to it from `AGENTS.md`:

```markdown
## Working with the owner
When the owner is carrying a goal end to end (scoping, spec, prototype, code, test, wrap-up),
read `docs/skills/baton-owner/SKILL.md` first and follow it.
Load the matching file under `references/` only when entering that stage.
```

Any other assistant that reads Markdown instructions can use the files the same way.

## How this relates to the two boards

Baton comes with two boards, each with its own guide for the AI:

| | For | MCP server / tools | Its guide |
|---|---|---|---|
| [Personal board](../personal-board/) | one person and their AI conversations | `personal-board` / `personal_board_*` | `personal_board_guide` |
| [Team board](../team-board/) | people on the team with each other | `team-board` / `board_*` | `board_guide` |

The split:

- **The board guides say how to record**: filing a conversation, logging results, stage starts and ends, pushing to
  the team board. Each MCP server delivers its guide to the AI by itself, as instructions and through its guide tool.
  You do not install them.
- **This skill says how to work**: what each stage has to produce, when it counts as done, when to stop and ask the
  owner, what to hand to someone else, what to keep from each round. It names the boards' tools but does not repeat
  their rules.

The skill works without the boards; keep the trail however your team already does. The boards work without the skill,
too, but then nothing tells the AI what "done" means for a stage.

## Make it yours

The skill is a generic base. Add your people and preferences in section 9 of `SKILL.md`, and let it grow: at every
wrap-up the AI proposes lessons worth keeping, and writes them into the reference files only after the owner confirms.
