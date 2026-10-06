# Test: test as you build, send problems back to Dev, close both together

Accepting someone else's delivery calls for a full test report and tickets. When the owner **builds and tests their own work**, most of that ceremony can go. These parts cannot.

## What you do

- **List first.** From the final spec and prototype, list the behaviors to test (page / state / action → expected). Each item must be something you can call right or wrong on its own. A module title is not coverage.
- **Operate for real.** Open the real page, take the real steps, look at the real result. A screenshot proves what was on screen, not that the feature works. Passing automation does not replace comparing against the prototype with your own eyes.
- **Problems go back to Dev.** Fix them in Dev (both stages open), then retest the same list item. No bug reports, no tickets, unless the fix is being handed to someone else; then write a report they can reproduce from.
- **A regression test added for a specific bug must be able to fail.** Put the bug back and it has to go red. A test that is always green is decoration.
- **Leave mechanical checks to scripts**: alignment, whether pages load, whether read-only really is read-only, whether a reset restores the data.
- **The owner commenting on real data while you fix on the spot is also Test**, alternating with Dev. Verify each comment is a real problem before changing anything; if the owner misread something, say so.
- External review (an app store review, say) is not Test. It is waiting time you do not control; record it separately.

## What it produces

- A checklist: every item marked pass / fail / blocked / not tested, with the symptom and retest result for each failure.
- The screenshots or read-backs behind it, kept in the same task folder as the checklist.

## Exit criteria

- Every item on the list has a result. Each failure is either fixed and retested, or has a written reason for staying.
- The core path has been walked in a **real environment** (production, or a real local run), not only on test data.
- **Whoever asked for it accepts it.** Subcontracted work is accepted by the owner, not signed off by the person who did it.
- Passed: Test and the Dev span behind it end together (log both ends).

## Lessons

- **For anything that syncs data, list everything that can happen on the other side and ask of each: "can we see it here?"** Created, completed, abandoned, rescheduled, paused, owner changed. Checking them one by one finds gaps that "the data came across" never will. When the owner asks "why is this missing here?", say honestly whether it was missed or a deliberate trade-off.
- **Each problem a review or test finds gets one minimal regression test.** Do not add tests for coverage numbers.

## Common loops

- The test exposes something Product never decided → back to Product / UI Design to decide it. Do not paper over it in Test.
- A fix touches something else → back to Dev, then retest every related item on the list, not only the one you changed.
