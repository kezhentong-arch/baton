---
name: personal-board
version: 1.0.0
---

# Personal Board guide — file every AI conversation under the work it belongs to

> **At the start of every conversation**: file it under a line / goal / stage, say so in one sentence and log the start (small talk and Q&A are not logged). Rules in section 1.
> **Read the whole guide first**: some clients show only the beginning of these instructions (the first 2048 characters, for example). If this text ends in `[truncated]`, or you cannot see section 7, call `personal_board_guide` before filing or logging anything.

Why log at all: one person runs a dozen AI conversations a day in parallel. When each one is filed under a line, a goal and a stage, opening the board shows where everything stands.
With a team board connected, the personal board is also the source for that person's part of it: changes pile up here and, at wrap-up, the AI pushes them after the owner nods.

Lines and stages are the owner's configuration; the value table in `personal_board_actions` is authoritative (by default four team lines plus one personal line, and five stages: Business, Product, Design, Dev, Test).
Work that fits no stage is logged with no stage (leave `stage` empty). A **personal line** (`personal: true` on the line in `personal_board_state`) has no stages and is never pushed to the team board.

See the tool list for tools; `personal_board_actions` is the reference for write parameters and value tables; `personal_board_guide` returns this guide in full.
Every entry carries `task` (what this conversation is doing, a few words) and `tool` (`claude` / `codex`). `occurred_at` empty means now; set it only when backfilling (ISO with an offset).
Writes take a `request_id` (UUID): when the outcome is unclear, retry with the same id and the same parameters; to change parameters, read the current state first. If the board cannot be reached, report the error — do not keep notes elsewhere.

## 1. At the start of a conversation: file it (judge first, ask only when unsure)

1. Read `personal_board_state`: goals in progress per line and their next steps. If `points_due` lists point tasks due today or overdue, remind as in section 5.
2. From the opening message work out the line, the goal and the stage to start in, and **say so in one sentence** ("I'm logging this conversation under G2 New-user onboarding redesign · Dev").
   If the human does not object, log `log kind=start`; if that stage is not open yet, `stage_start` it too (ask before entering a stage for the first time — section 3).
3. No goal fits, or more than one does: ask, do not guess. Small talk, Q&A and anything unrelated to a goal is not logged.
4. A new goal is created with `goal_create` and gets a **birth number** on the spot (the owner's letter + a sequence, e.g. A19; it never changes and is never reused).
   A goal on a team line is pushed to the team board at wrap-up (with its birth number); afterwards `goal_update gnum=G…` switches the display number, and the birth number still finds the goal. Commit messages may cite it.
   - **Ask for the planned finish separately and suggest a date.** Leave it empty only when the human says it cannot be set yet; "empty for now" is not the default. It may go down to the hour (`2026-10-02 08:00`, main time zone).
   - **You decide whether to write "What", without asking.** Leave it empty when someone uninvolved can tell from the title what is to be achieved and when it counts as done (always empty for point tasks).
     Otherwise pass `what`, one or two sentences: the outcome + how to tell it is reached (a checkable criterion, not the implementation).
     Example: "Onboarding redesign" → "A new user adds their first pet within three steps; done when sign-up-to-first-pet reaches 60%."
   - **Shipping and upkeep are separate goals.** A shipping goal closes when v1.0 is usable. Ongoing upkeep of a tool or handbook is its own **long-running row**
     (`long_term`, not under the shipping goal; to keep it off the team board, mark its creation entry `sync_mark status=skip` right after creating it). Only then can shipping goals finish on time.

## 2. How much to log

- One entry when **starting** (`kind=start`).
- One per **visible result** (`kind=result`): a page runs, a document is final, a test round is done, a plan is agreed. Not sentence by sentence — rarely more than two or three an hour.
- One when **wrapping up** (`kind=wrap`): what this stretch did, and the next step.
- One **digest** (`kind=digest`, a gold dot on the timeline; green is reserved for a completed goal) when a lesson or rule was written into a handbook or knowledge base. Write "Handbook x.y.z: what was added".
  Log it on the goal the work belongs to; if the owner has a long-running handbook row, log it there. **Only long-running rows take `version`**; on an ordinary goal it is rejected.
- Stages start and end with `stage_start` / `stage_end`. Several may be open at once; going back and forth is logged as it happens and is not a step backwards.
- When a goal's next step changes, `goal_update next_step`; the start-of-day list is built from it.

**At completion and when closing a version, write "Done"** like an app's "What's new": short, plain words about the changes a user can see, one per line —
no process, reviews, test counts or commit ids. You decide whether to write it; leave it empty when the title says it all. Write it once, at completion or close; edit later with `goal_update what= / done_what=` only if the human asks.
- Ordinary goal: `complete` with `done_what` (open stages end with it). An abandoned goal says why in `reason` with `status=abandoned`.
- **Long-running tool row** (ongoing upkeep of a tool): a change counts only once the human has looked at it. For each round open Dev → Test on that row, end the stages when the human accepts,
  then log a `release` (`version` = the new badge, `text` = what this version did). The **version badge** changes with it and the detail page's changelog gains a version.
  Size the number by the change: bug fixes and small tweaks bump the patch (v1.1 → v1.1.1); a real feature bumps the minor (v1.2). Say which number you propose when starting; the human decides.
- **Long-running handbook row**: each edit is done once written — log a `digest` with `version` ("Handbook 1.2.0"); the badge changes with it.
- The badge is always the highest-numbered version. On a row that is not pushed, stage entries are not marked "unpushed".

## 3. Stage gates

- Before entering a stage **for the first time**, list what the previous stage produced and what is missing ("Is Product done? Spec final, you reviewed it — X is missing. Move on to Dev?").
  `stage_start` only after the human agrees. Half-finished may proceed if the human knows what is missing; broken may not. Going back and forth (a test fails, back to Dev, test again) needs no question — just log it.
- When starting and when wrapping up, check every open stage: list what is done and what is missing, and ask whether to end it or move on.
  If the human is plainly doing the next stage's work without saying so, mention it right away.
- Never decide a goal's owner, stage or line for the human, and never guess missing information.

## 4. Wrapping up: when the human says "wrap up" / "done for today"

0. First ask whether this round produced a lesson worth writing into a handbook, and list candidates; write only after a nod, then log a `digest` as in section 2.
1. Read today with `personal_board_state`, write a one-sentence summary and log it as `wrap`.
2. **No team board connected** (`header.team_board` is false): you are done. An empty `personal_board_pending` is normal; do not mention "unpushed".
3. With a team board: list the unpushed entries from `personal_board_pending`, grouped by goal (goal, what, when).
4. After the nod, **push them one by one through the team board's own MCP** (its write tool, `board_act` on the `team-board` MCP server; action names and parameters follow the team board's own action reference — this table is the usual mapping):

   | Personal-board entry | Team-board action | Carries |
   |---|---|---|
   | `goal_create` (team line) | `create` | title, owner, line, parent (its id on the team board), `due` (with the time, as is), `occurred_at`, `source` (the birth number: `birth` in the pending list), `note` (the "What": `goal_what`; omit when empty) |
   | `stage_start` / `stage_end` | `start_stage` / `end_stage` | the goal's team-board id, `stage`, `occurred_at` |
   | `due` | `change_due` | goal id, `due` (with the time, as is), `reason` (put the reason into `reason` when logging the change) |
   | `abandon` | `abandon` | goal id, `reason` |
   | `complete` | `complete` | goal id, `occurred_at`, `done_what` (`goal_done_what`; omit when empty) |
   | `summary` (a pushed goal's "What" / "Done" changed; one entry per goal) | `edit_goal` | goal id; `note` for "What", `done_what` for "Done" (send an explicit empty string to clear) |

   Find the goal's team-board id in the team board's own state by its G number and verify it. **Never use this board's internal goal_id** — the two numbering schemes differ.
5. After a successful push, `sync_mark` (`entry_ids`, `status=pushed`, `team_ref` = the event id returned). A newly created goal gets its G number: `goal_update gnum=G…`.
   If the team board refuses, relay its message as is and leave that entry unpushed; do not force it.
6. The human says an entry should not be pushed → `sync_mark status=skip`, or `void` it and log again (voiding a "complete" does not reopen the goal; use `goal_update status=active`).
7. When a stage really changes hands mid-day, ask on the spot whether to push those entries now.

One conversation owns a wrap-up; the others keep logging and do not push the same list at the same time. The personal board never writes to the team board itself — the team board's MCP is the only way in.

## 5. Dictation and point tasks

**Dictation box**: saving a dictation on the page copies "Please log the dictation below on my personal board (dictation #N)…". On receiving it: read the original from the dictation list in `personal_board_state`
→ match it to a goal and a stage → ask about anything missing → log with `personal_board_act` → `note_resolve` with one sentence on what was logged → tell the human.

**Point tasks**: things done once at a moment (e.g. paying contractors on the 1st of each month). The timeline shows a hollow dot when it reaches the moment, solid once done,
red with "N d overdue" while overdue. **Never pushed, no stages, no planned finish** (the board rejects those).
- Create: `goal_create` with `point_at` (the first moment) and `point_zone`, plus `repeat=monthly` for a monthly one. Ask for the day and the line first;
  if no time was given, pick one and say so; with two zones configured, ask whose wall clock applies (so daylight saving never shifts it by an hour) — default is the main zone. Then tell the human the next occurrence.
- Tick: when the human says "Y is done", `point_done` (with no occurrence named, the earliest one not done). Ticked by mistake: `void` that entry.
- Remind: when work starts and `points_due` has items due today or overdue and `reminded_today` is false, mention them in one line (use the `say` it gives),
  do not press, then log `point_reminded`. Once a day; an overdue one is mentioned once every day.
- Change the day with `goal_update` (`point_at` / `point_zone` / `repeat`); to stop doing it, `goal_update status=abandoned`.

## 6. Numbers

- The **birth number** (letter + sequence, e.g. A19) is a goal's identity on the personal board and still works after the goal is pushed; the display number then becomes the team board's G number.
  The page shows both (`A19 · G2.3`). When talking to the human or writing commit messages, prefer the birth number — it never changes.
- A team-board level number (G2.3) is a position and changes if the goal moves under another parent; mention the title with it, never a bare number.

## 7. House rules

- When asking the human to confirm a moment, convert it with `personal_board_time`; with two zones configured write both (its `both` line), with one write the one.
- Conversations in Claude Code and in Codex both follow this guide. Several conversations write to the same board; each entry's `task` / `tool` tells them apart.
- Talk to the human in product language: say what will show on the board, not field names or commit ids.
- Entries made in practice mode (an MCP server started with `PERSONAL_BOARD_PRACTICE=1`) are not real; never push them to the team board.
- After the board's code changes, conversations already open still run the old MCP code; new conversations pick up the change.
