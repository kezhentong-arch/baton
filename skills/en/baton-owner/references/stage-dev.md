# Dev: get it running first; not done until self-tested

How to write code is governed by the repo's own engineering and testing conventions. This file adds only what changes when the owner does Dev with AI.

## What you do

- **Decide where it belongs first.** Code goes in the module it belongs to; if it belongs nowhere, give it its own directory instead of squeezing it in.
- **Make the technical calls yourself** and report them in one sentence. Do not ask a non-technical owner to choose.
- **Get it running first; no big builds.** Running and verifiable beats tidy architecture. No scaffolding nobody needs.
- Halfway in and Product never decided something → back to Product / UI Design. Do not improvise in code.
- Several conversations editing one repo: one working copy each (git worktrees, for example). Commit only the paths you changed; never `git add -A`.
- **Changes that touch production or data** (adding or removing an endpoint, a schema change, a deploy): say what will change, why it cannot be avoided, and whether it can be rolled back. Proceed only on a yes. Back up before a schema change and run it in a test environment first.
- **Show UI changes in a local test environment first, ship after the owner nods, then read production back to confirm.** The test environment runs on a copy of the data with no production storage, notifications or external services. Do not add production credentials to make it "look more real": deletes, uploads and notifications made there would then hit production.
- Subcontract what you cannot do (typically backend, production services, data migrations): get your part running, then write down exactly what is missing (see section 5 of the main skill).
- Log each visible result (the page opens, the endpoint responds, the data arrives) on the personal board.

## What it produces

- Something that runs locally, how to start it, and a minimal regression test for each specific failure fixed.
- Committed and pushed to the team's main branch.

## Exit criteria

- **It runs.** You started the service or ran the command and saw a real screen or result (screenshot, read-back). "Tests are green" does not count.
- **Self-tested.** You walked the main path yourself and fixed the obvious breakage.
- The repo's own checks pass (lint, tests, docs in sync).
- Committed and pushed; others can pull it.
- Anything unfinished is written down. Never "basically done".

## Lessons

- **Screenshot every UI change with a headless browser before showing it**, small ones included; small changes break neighbors too. Measure alignment and count expected elements with a script, not by eye.
- **Get one independent review before the owner sees it.** Ask it to test in a real browser on throwaway data and to report failing scenarios. Serious bugs that only a normal workflow triggers do not show up when you reread your own diff.
- **A small style fix gets three checks**: the problem is gone; nothing else changed (run the old version on the same data and compare pixel by pixel); nothing was overcorrected (what should show still shows). Prove each check can fail by running it against the old or a deliberately broken version.
- **When one rule is implemented in two places**, search both before changing either. If the two must match exactly, feed both the same batch of inputs and compare every output. A handful of examples is not proof.
- **Anything built for other people** (samples, tools) works offline and is not tied to a particular person. Before handing it over, run it start to finish in a temp directory as if on their machine. Repeat as them after every release.
- **Disable built-in browser behavior** (swipe-back, zoom, context menu) only on the page that needs it, never in shared styles. Check the pages reachable from that page first.
- **When a category is renamed, do not rewrite old records.** Translate on read through a mapping table. History stays intact and old data does not fight new rules.
- **For changes queued to sync later**, keep one unsynced entry per item and overwrite it on the next edit. At design time ask: "what happens if the same thing is edited twice?"

## Common loops

- Self-testing finds a problem → still Dev; fix it.
- Test sends a problem back → fix it in Dev, test again (both stages open; log them as they happen).
