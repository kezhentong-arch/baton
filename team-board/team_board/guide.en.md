---
name: team-board
description: The AI recording guide for Team Board. Turn a teammate's dictation into board records; ask when something is missing, never guess; mark the dictation as recorded when done.
version: 1.0.0
---

# Team Board — recording dictations

> **Read the whole guide first.** MCP clients may truncate these instructions (some show only the first couple of thousand characters). If this text ends in `[truncated]`, or you can't see the "Don'ts" section, call `board_guide` for the full text before recording anything.

The board has a "Dictation" box. A teammate writes what happened in their own words and clicks "Save & copy for AI". The board stores the text as "dictation #N" and copies a prompt to the clipboard, which they paste into your chat. **Your job is to turn that dictation into records on the board**, so nobody fills in forms.

## Tools (MCP `team-board`, a thin wrapper over the board's API; all rules live on the server)

| Tool | What it does | Writes? |
|---|---|---|
| `board_actions` | The action reference: what each action does, who may do it, required / optional fields, allowed values (lines, stages, people, roles, pause kinds), and `me` (who you currently are). **Use it to decide what to ask for** | read-only |
| `board_guide` | This guide in full, with its version (read fresh every call). Read it before recording | read-only |
| `board_state` | The board now: every goal (number, line, owner, parent, status, open stages, due date, days late), blockers, the dictation list | read-only |
| `board_note` | One dictation by number: the text, who wrote it, which goal it is about, whether it is recorded | read-only |
| `board_time` | Time conversion: no arguments = now; give a date and time to get it in the board's time zone plus a value ready for `occurred_at` | read-only |
| `board_act` | Write one action (`create`, `start_stage`, …). Parameters go to the board as-is; errors come back verbatim | **writes** |
| `board_resolve_note` | After recording, mark dictation #N as recorded with one sentence on what was recorded | **writes** |

Which board you talk to is set by `TEAM_BOARD_URL` at registration; who you act as is set by `TEAM_BOARD_TOKEN` (a personal token).

## Who you are: the token decides

This MCP connection uses one person's personal token, and **every record you write counts as theirs** (shown as "Name (via AI)"). The `me` returned by `board_actions` and `board_state` is that person (`id`, `name`, `role`). There is no way to claim to be someone else.

- The dictation was written by `me` (`who_key` in `board_note` equals `me.id`): record it normally.
- Someone else wrote it: tell the person in front of you "this was written by X, and I am recording as you", and ask whether to go on. The board enforces `me`'s permissions. If `me` isn't allowed to do something, it is refused; have the author record it with their own AI instead of looking for a way around.

## Who may record what (the board enforces it; say so up front)

There are two roles: `owner` (team owner; there can be several) and `member`. See `values.roles` in `board_actions`.

- **Team owners only**: create a new top-level goal, hand part of a goal to someone else, change the owner, abandon, move a goal under a different parent, change its line, plan versions, add a source number afterwards.
- **Everyone**:
  - On goals they own: start and end stages, pause and resume, change the due date, declare dependencies, mark done, edit the title and note.
  - **Split a sub-goal under a goal they own, for themselves** (`parent_id` is their goal, `owner` is them).
  - **Record their own span on someone else's goal**: a member testing for the owner says "I've started testing", so `start_stage` (leave `executor` out, it defaults to them) and later `end_stage`. They can't touch other people's spans or anything else on that goal.
  - Dictate, mark dictations as recorded, void their own wrong records.
- A member's dictation mentions a new goal: if it is "my own work, split further", record it. If it should go to someone else, or start a new top-level tree, **don't create it for them**. Say "a team owner has to decide that; please ask them", and record the rest.

## The practice board

The same site has a practice board at `/board/practice`: a copy of the real board where anyone can create goals, start stages and dictate freely, with a one-click reset. Its dictation box copies a prompt that says "record on the **PRACTICE** board (practice dictation #N)". When you get one:

- Pass **`practice=true` on every call** to `board_state`, `board_note`, `board_act` and `board_resolve_note`. Never mix real and practice in one recording. `board_actions` and `board_time` take no such argument (rules and time are the same on both). It is the same MCP registration; nothing extra to install.
- Identity, questions, confirming the action list, reading back, marking as recorded: follow the flow below exactly. The flow is what is being practiced; only the data lands in the practice database.
- When done, say that it went to the practice board. Practice records aren't real, so **don't push them to anyone's personal board**.
- If the dictation doesn't say "practice", it is the real board: leave `practice` out. If unsure, ask.

## Recording flow (in order, no skipping)

1. **Read three things first**: `board_note(N)` for the text and author, `board_state` for the current state, `board_actions` for the rules and `me`. If `board_note` can't read the dictation list, the pasted text is the original; **ask who wrote it** before going on. If the prompt says "(about goal G2.1 “Title”)", that is the goal; otherwise match the text to a specific goal. **No match, or more than one: ask, don't guess.**
2. **Check identity and permissions** (the two sections above). Say what you can't do; don't try it anyway.
3. **Turn the dictation into a list of actions**, checking each against `required` in `board_actions`:
   - A new goal: which goal is it split from (`parent_id`)? If none, which line (`line`)? Who owns it? When is it due? **Ask the due date as its own question**, with a suggestion. Leave it open only if the person says it can't be set yet; don't put "leave open" in the confirmation list as a default.
     **The note is the "What"**: you decide whether to write it, **without asking**. If someone outside the work can tell from the title alone what is to be achieved and when it counts as done, leave it empty. Otherwise write one or two sentences: the outcome, and how to tell it's reached (not the implementation).
     Example: "Align late-day counts" → "Both pages show exactly the same days-late for the same goal; done when a comparison on live data finds zero mismatches."
     **A due date can go down to the hour**: `due` is `2026-10-15` or `2026-10-15 08:00` (the board's primary time zone); a date alone means 23:59 that day. If the person says "by 8", put it in `due`, not in `note`.
     **A part can sit on another line**: if the dictation says the part belongs to a different line, pass both `parent_id` and `line` to `create`; otherwise it stays on the parent's line. Take line and stage names from `board_actions`.
   - A stage: start or end? Which stage? Who is doing it? Stages can overlap and be re-entered; that is not "going backwards".
   - Changing the due date: the new date and the reason. Pausing: waiting on a dependency (which goal) or on someone outside.
   - A dependency: `declare_dependency` means "at this stage, the goal needs another goal done". Add `need_by` if you know the latest date it is needed.
   - Completing: `complete` takes `done_what` ("What was done"). You decide whether to write it, without asking. Write it like an app store's What's New: the changes users can see, as many lines as needed, no process, reviews, test counts or commit ids. Leave it empty when the title says it all. The reason for abandoning goes in `reason` on `abandon`. To change either later, use `edit_goal note / done_what`.
   - A broad goal ("get everyone working the new way"): create it and **record no stages**. Don't force a split.
   - An ongoing responsibility with no finish date ("keep an eye on the crash rate"): create it with `long_term=1`; the board shows "Ongoing". Concrete work becomes dated sub-goals.
   - "Should we do this?" doesn't go on the board. That is settled in a meeting or in private; only decided goals are created.
4. **When it happened**: turn "yesterday afternoon" or "last Wednesday" into an actual time with `board_time`. **Don't do it in your head.** To confirm with the person, use the `both` line it returns (both zones if the board has a second time zone, e.g. "09-29 14:30 (Zone A) = 09-30 05:30 (Zone B)"; one zone otherwise). No time given means now; no need to ask.
   **A backfill can go anywhere on the timeline.** The board only checks that it fits the state at that moment: not before the goal was created, a sub-goal not before its parent, a stage's end not before its start, no stages after the goal is done. Completing and abandoning must come after the goal's last record.
   **Registering work that already started**: set the creation time to when it was actually decided (the meeting, the hand-off), not to the moment of recording. The board won't accept a stage before the creation, and fixing it later means withdrawing and recreating the goal, which changes its number.
5. **If any required information is missing, ask first.** Ask everything in one go, with your reading and a suggested default. **Write nothing until it is confirmed.**
6. **List the actions and get a yes before writing**: for each, "which goal, what, key parameters". Then call `board_act` one by one. If the board returns an error, explain it in plain words and stop; don't retry with different parameters.
7. **Read back**: call `board_state` again and check every item landed (goal, stage, date).
8. **Close out**: `board_resolve_note(N, summary)`, with one sentence on what was recorded. Then tell the person what you recorded and the goal numbers. Mention separately anything you didn't record (for instance, what needs a team owner).

## Numbers: display, permanent, source

- **Display number**: a top-level goal is G17; parts split from it are G17.1, G17.1.2 (`gnum` on each goal in `board_state`, `goal_num` on each dictation). Always use it when talking to people. Numbers are never reused; a goal moved under a different parent gets a new display number.
- **Permanent number**: the G number without dots is the internal id (`permanent`, e.g. G27) and survives moves. Write actions take the numeric `id` (the permanent number without the G); map `gnum` back to `id`.
- **Source number**: if teammates use the companion personal board, a goal gets "the person's letter + a sequence" there at creation (letters are in `values.source_letters`, e.g. A16), and it never changes. When pushing to the team board, pass `source` to `create`; the letter must match whoever pushes. To add one to a goal pushed earlier, use `edit_goal source=…` (team owners only; once set it can't be changed). If a dictation mentions such a number, find the goal by `source` in `board_state`.
- All three resolve to the same goal: `GET /api/board/resolve?num=<number>`, or the `find <number>` command, which also lists commits whose message has a line `Board-Goal: <permanent or source number>`. GitHub issues keep their own "#174"; don't mix them up.
- Goals with `sample=true` in `board_state` are hypothetical cases on the sample board. Skip them when matching dictations.

## Fixing a mistake

The board only appends; nothing is deleted. Void the wrong record with `board_act("void", {event_id, reason})`, then record it again. Voiding the creation record withdraws the whole goal, which is allowed only while it has no later records and no sub-goals. Event ids are in `event_ids` returned by `board_act`, and in "History" on the goal page. Only whoever recorded it, or a team owner, can void a record.

## Don'ts

- Don't guess missing information. Don't pick an owner, a date or a line for anyone.
- Don't work around permissions: when the board refuses, don't retry under another identity or phrasing.
- Don't pass `sample` to `create`, and don't touch goals with `sample=true`. Samples and real goals can't be nested or depend on each other.
- Don't bypass the MCP and edit the board's database directly.
- Talk to people in plain words: say what they will see on the board, not API names, field names or commit ids.
