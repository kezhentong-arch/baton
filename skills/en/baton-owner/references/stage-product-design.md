# Product and UI Design: spec and prototype settle each other

Two stages, one file: when an owner does Product, the work usually lands in a prototype, and the two alternate and overlap. But **each has its own exit criteria and is timed separately on the board.**

## Two ways in (same exit)

| Route | When |
|---|---|
| **Spec first, then prototype** | The idea is mature: write the requirements in full, then build the first complete prototype |
| **Prototype first, then spec** | A one-line idea or a small iteration: take stock → change the prototype → owner reviews → finalize → update the docs |

Either way, **the prototype is the anchor**. For anything with a screen, update the spec to match the prototype the owner approved, never the reverse. For anything without a screen, the spec itself is the deliverable.

## Product: what you do

- **Take stock first.** Look for existing capabilities, pages and docs before proposing anything new. Write "what it is now" and "what it should become" separately, and label the present as the present, not as a rule ("we currently ship weekly" is not "we must ship weekly").
- **Split requirements into three layers**: product goals (must hold), existing behavior to keep (preserve as is), and technical approach (reference only; decided in Dev). Bring the owner product questions only, each with a recommendation.
- **Write requirements** as user-visible behavior, business rules, copy, and who gets notified. Each item states now / change to / why. No chat tone, no implementation detail.
- Version the document and add a changelog line with every edit.

### Product exit criteria

- The spec is final; the owner has read it and said yes.
- Every item has now / change to / why, with no placeholders ("this section later" is not final).
- Affected product docs are updated to match (for anything with a screen, once, after the prototype is final).

## UI Design: what you do

- Build this round's prototype: a single-file page, or a clickable page running locally. Send screenshots after each change; the owner comments on the prototype, and Product and UI Design change together.
- **Show a page with real data, not a static mockup.** Examples should look like real use. If production data exists, run locally on a copy of it.
- **Reuse what is proven before inventing**, but reuse is not copy-paste: think about who uses this screen and how.
- **Verify feedback before acting on it.** Separate the problem from the proposed fix: problems get fixed, proposed fixes get your honest assessment. If the owner misread something, say so.
- **One visual signal, one meaning.** If a highlighted row means "selected", do not also use it for "expandable".
- **Give something its own row only if it carries information its parent cannot.** For a one-to-one containment, leave a marker on the parent instead.
- Version the prototype and note what changed each round.

### UI Design exit criteria

- The owner has seen the prototype and said yes (a screenshot, or they clicked through it themselves).
- The prototype is saved where the team can find it (merged, or in an agreed folder).
- Prototype and spec agree.

## Lessons

- **Material meant for other people uses screenshots of the latest live version.** Screenshots left over from development were for review; if they differ from what people see when they open the product, they confuse. Send one format only.
- **When a structure or category name changes, put the intro page and tutorials on the same change list** and ship them in the same round. Do not wait for someone to notice.
- **For features where people submit something (register, file, report), default to "tell your AI".** The page keeps a short note on what to cover and a prompt to copy to the AI. The AI asks for whatever is missing, submits through the system's MCP, and does not ask about things it can see for itself. **Review and judgment stay on the page, clicked by a person**; the AI does not pre-fill a suggested verdict for the reviewer.

## Common loops

- Reviewing the prototype overturns a product rule → back to Product: change that item in the spec, the prototype follows, bump a minor version.
- Dev finds a state the prototype never defined → back to UI Design to define it. Do not improvise in code.
