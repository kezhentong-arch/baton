# Business: say what is to be achieved, then create the goal

Business sets the goal. The goal comes first: until the outcome is settled, Product, UI Design, Dev and Test have no direction. The boards start at "a concrete goal we decided to do". Higher-level directions ("steady user growth") stay off the board; people break them down into concrete goals.

## What you do

- Turn the initiator's words into a one-sentence **goal**: the outcome + **how to tell it is reached** (a checkable criterion, not an implementation). Example: "Vaccine reminders" → "Owners get a reminder three days before a vaccine is due; done when delivery to due users holds at 95% for two weeks."
- Ask: which line, which goal it is split from, who owns it, and where to pause for review (e.g. the initiator reviews the spec once it is final).
- **Ask for the planned finish as its own question, with a suggested date.** Leave it open only if the owner says it cannot be set yet; "open for now" is not the default.
- **Whether to do it is decided outside this flow** (a meeting, a private chat). Never create a goal on someone's behalf. Once it is decided, create it as the team board's guide (`board_guide`) describes; that guide also says who may.
- **Too big? Split it into blocks.** The parent exists first, then its blocks. A block may sit on another line. How a block is split further is up to that block's owner.
- When the initiator does only Business and hands execution to others, the initiator still owns the parent goal and each executor owns a block under it. "Give this to Ben" means execution, not a change of owner on the parent.
- When handing someone a whole package, the "What" states only the outcome. Approaches and examples the initiator mentioned in passing are hints, not requirements.
- A broad initiative (get everyone working the new way, learn a tool) is still a goal: log its start and end, no stages.
- An ongoing responsibility (keep an eye on the crash rate) is created as long-running; concrete work becomes dated sub-goals.
- A sub-goal does not repeat the Business stage its parent already did. If the parent made the outcome clear, the block starts at Product or Dev.

## What it produces

- A goal on the board: title, line, owner, parent, planned finish. On the personal board, the same goal plus a next step.
- The goal sentence (outcome + how to tell) goes into the board's "What". Skip it when the title says it all.

## Exit criteria

- The goal exists, with a clear line, owner and parent.
- "How to tell it is reached" is written in one sentence and the initiator agrees.
- Review points are agreed (at minimum: who looks at the spec when it is final).
- The planned finish is set, or explicitly recorded as "to be decided".

## Business overview: when there is too much to hold in your head

When an abstract direction has to land as concrete work, or there is more going on than anyone can track, run one overview round. It is a Business deliverable; every block it identifies becomes its own goal afterwards.

- Six parts: where we stand now, what the business is made of, rules already settled, blocks and their dependencies (what can run in parallel, what must come first), messages to align with others (written so they can be forwarded as is), and what is still open.
- Review it in conversation with short questions and short edits. Produce the formatted document only when the owner says "final"; later edits bump its minor version.
- Append the owner's own words to the final document: deduplicated, grouped by topic, edited as little as possible. When someone later asks "why did we decide this?", the source is there.

## Common loops

- Product work shows the goal is too big → back to Business and split it. The original goal's criterion stays as it was.
- A block belongs on another line → create it with both its parent and its line (parameters in `board_guide`).
