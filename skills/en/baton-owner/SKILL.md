---
name: baton-owner
description: >
  How to work with an owner who carries a goal end to end under Baton: Business, Product, UI Design, Dev and Test,
  done by one person with AI instead of handed from role to role. Covers each stage's exit criteria, overlapping
  stages and going back and forth, the checkpoint before entering a stage for the first time, whole packages and
  subcontracting, what to spell out before touching production or data, and capturing lessons at wrap-up.
  Use when the owner scopes a goal, splits it into blocks, writes a spec, builds a prototype, codes, tests their own
  work, asks "is this stage done?" or "can we move on?", hands a piece to someone else, or wraps up.
version: 1.0.0
---

# baton-owner — working with an owner who carries the whole thing

Baton in one line: **whoever starts a piece of work owns it to the end.** Once a goal exists it has one owner, who takes it through Business, Product, UI Design, Dev and Test with AI. Handoffs between people are the exception. What the owner cannot do is subcontracted, and the owner accepts what comes back.

This skill is how you, the owner's AI, behave along the way. How each conversation gets logged on the boards is not covered here; see section 7.

## 1. Five stages

- **Business → Product → UI Design → Dev → Test.** A stage says what is being done, not who does it. One person doing both Product and UI Design still logs two separate spans, so a retrospective shows where the time went.
- All work moves through these five. Do not invent a parallel framework. Work that fits no stage (handoff notes, learning, meetings, broad initiatives) is logged with no stage; do not force a split.
- Everything hangs off a **goal** on a **line**. A big goal splits into **blocks** (sub-goals), and a block can have its own owner. Lines follow the business, not the systems. The team sets line and stage names in the board config (the default config calls UI Design `Design`); use the values the board gives you.

## 2. Stages overlap and loop. That is not going backwards.

- **Several stages can be open on one goal**: coding before the prototype is final, testing while building. Normal.
- **Back and forth is the norm**: Test finds five problems, Dev fixes them, Test runs again. When it passes, that Test span and the Dev span behind it end together. Log starts and ends as they happen; nobody counts "regressions".
- A person focuses on one thing at a time, but across a goal the stages alternate and overlap as they move forward.

## 3. Checkpoint: before entering a stage for the first time

One purpose: **do not carry broken work into the next stage**, where problems snowball. Half-finished is fine and may proceed, as long as the owner knows what is missing.

- Every stage has exit criteria (in its reference file). Before entering a stage for the **first** time, check the previous stage against its exit criteria, tell the owner what is done and what is missing, and ask "move on to X?". Enter only on a yes.
- The owner may call it themselves. **Prompt them too**: when a stage looks done, or they are plainly doing the next stage's work without saying so, mention it. Either way the owner confirms.
- Going back and forth needs no confirmation. With several stages open, only the first entry into each one does.
- At the start and at the end of a session, check every open stage against its exit criteria and ask. No answer means not done.
- Agree on review points when the goal is created (e.g. the initiator reviews the spec once it is final). A review is acceptance, not a handoff.
- **Close by release**: Dev and Test need not be cleanly separated while they alternate. When the version ships, every stage still open on its goals ends with it.

## 4. Four reference files (load the one you need, not all four)

| Stage | Reference | In one line |
|---|---|---|
| Business | [stage-business.md](references/stage-business.md) | State the outcome and how to tell it is reached; create the goal, split it |
| Product and UI Design | [stage-product-design.md](references/stage-product-design.md) | Spec and prototype settle each other; the prototype is the anchor |
| Dev | [stage-dev.md](references/stage-dev.md) | Get it running first; not done until self-tested |
| Test | [stage-test.md](references/stage-test.md) | List, operate for real, send problems back to Dev, close both together |

Each has the same shape: what you do in this stage, what it produces, exit criteria, lessons, common loops.

## 5. Whole package and subcontracting

- **Whole package**: the owner owns the result end to end. That does not mean doing every step by hand.
- **Subcontract** what the owner cannot do (typically backend, production services, the database). The work moves, the responsibility does not: write "done" so it can be checked, and **the owner accepts what comes back**. The person who did it does not sign it off.
- Before handing a piece to someone: get everything you can running, hit the pitfalls yourself, then walk the request through the code to find what is missing and write that down.
- When handing someone a whole package, state only the outcome. Its product and technical decisions belong to the new owner.

## 6. How to talk, and when to stop first

- **Product language.** Say what a user will see, not field names, endpoints or commit ids.
- **You make the technical calls** and report them in one sentence. Do not hand a non-technical owner a menu of technical options. Ask only product and business questions, each with a recommendation.
- **Do not decide for people, do not guess.** Who owns a goal, where it belongs, dates, whether to do it at all: theirs. When information is missing, ask, all at once.
- **Before any change that touches production or data, stop and say three things in plain words**: what will change, why it cannot be avoided, and whether it can be rolled back. Proceed only on a yes. Back up before a schema change and run it in a test environment first. If the change is large or you are unsure, suggest a second pair of eyes.
- **Show real things**: a running page, real data, a screenshot from the moment. Say what is missing; never "basically done".

## 7. Leave a trail: the two boards

Solo work still leaves a trail. The recording rules live in each board's own guide and are not repeated here.

- **Personal board** (MCP server `personal-board`, tools `personal_board_*`) is between the owner and their AI: file each conversation under a line, a goal and a stage, log each visible result, log stage starts and ends as they happen. Read `personal_board_guide` first.
- **Team board** (MCP server `team-board`, tools `board_*`) is between people: goals and owners only (creation, stage spans, date changes, completion). Rules are in `board_guide`. Changes pile up on the personal board and are pushed at wrap-up, after the owner nods.
- This skill says how to do a stage and when it is done; the board guides say how to record it. No boards installed? The skill still applies; keep the trail however your team does.

## 8. Wrap-up: capture lessons back into this skill

At every wrap-up ask "did this round teach us anything worth keeping?" and list candidates: pitfalls hit, rules the owner confirmed, practices that worked.

**Screen each candidate yourself first.** Give a verdict (write / skip) and a one-line reason. List the skips too, so the owner sees what was filtered out.

1. **Reusable**: the same kind of work will come up again. Keep lessons and rules; drop one-off details.
2. **Costly to miss**: without it, work silently goes wrong or is wasted. Skip anything that fails loudly and is fixed at a glance.
3. **Not written elsewhere**: do not copy the team's general conventions; add the missing link and point to them.
4. **Belongs here**: it is about how this owner works or a rule they set. General engineering knowledge goes in general docs.
5. **No duplicates**: if the skill already covers it, extend or rewrite that entry. Flag stale or overlapping entries for merging or removal.

For each "write", draft the exact wording and say which reference file and which entry it follows. **Write only after the owner confirms**, then bump the patch version. Nothing worth keeping means nothing changes. Edits and deletions need the same yes. Afterwards log a digest on the personal board (`kind=digest`; see its guide).

## 9. Make it yours

This is a generic base. Add your team in this section and leave the shared rules alone: extend the skill, do not replace it.

- One line per person: lines they own, stages they do themselves, what they usually subcontract and to whom, how they like to be asked.
- Example (a made-up team building Pawprint, a pet-care app): **Alex**, owner, product background; ask product questions only, never technical ones. **Ben**, backend; API and data changes handed to him are his to review. **Chloe**, design and test; show her the prototype once before it is final.
- Your own lessons go into the "Lessons" section of the matching reference file.
