# The Handoff Is the Bug

*Owner mode: how a small team works once everyone has Claude Code*

Cao Tong

## AI writes at lightning speed. So why is everything still slow?

If you work with AI, you probably know the feeling. The AI writes code, builds pages and runs tests at a startling pace. Yet getting a thing from "let's do it" to "people are using it" hasn't sped up much at all.

Our team has done all of its development in the terminal with Claude Code since day one. We should have been fast. But when I recently looked back at how our device-fleet social media growth system shipped, it had landed far behind plan.

A word on what that system is. The name says most of it: a locally deployed GUI model reads the screen and taps it the way a person would, running a whole fleet of devices automatically to do operations and growth work on social media. It can do growth for any product. Below I'll just call it the growth system. It has three parts: a web app for people, an execution layer that operates the devices, and the device-control foundation the execution layer depends on.

The plan said "in use this week." It said that for several weeks running. Go back further, and our app took far longer than expected to get from first commit to launch, and then sat stuck in testing for a long time.

Claude Code wasn't the problem, and neither were the people; everyone worked hard. After thinking about it for a long while, I concluded that the problem was the way we worked together.

## The old way: a relay race

For decades the standard practice in software has been to split work into stages. One person figures out the business need and writes the spec, hands it to the next to build, who hands it to a third to test. A relay race: at every leg, a new runner.

We worked that way too. Every loss we took happened at the handoff.

- **You don't know what to hand over.** When I passed something to our engineer, I often didn't know what information he would need. I spent a great deal of time writing specs and filling in documents, and things still went missing, because much of what matters the writer doesn't even realize needs writing down.
- **You learn what's missing only when the other person hits the wall.** Halfway through, something turns out to be missing. It comes back to be filled in, then goes over again. The other person has other work, so it waits in a queue. One round trip, and days are gone.
- **Even what you did hand over gets lost.** How the web app and the execution layer of our growth system connect was all there in the complete prototype I had built. It was a working, clickable prototype, not a set of pictures. That piece still got lost after the handoff, and nobody noticed it hadn't been built until the very end. It fell exactly between two runners.
- **Testing piles up at the end.** A big batch gets built and only then handed to testing, so every problem lands on the home stretch. The last bit is far harder than anyone estimated.
- **Everyone queues for the same person.**

Everyone was conscientiously responsible for their own leg: catch what comes from upstream, explain your part clearly to downstream. And a great deal of brainpower went into the explaining.

One more thing. While a product is small, none of this shows much. A fresh demo that grows from zero, one piece at a time, gets by fine with a relay. But once you are dealing with a complex system that has already taken shape, what needs explaining multiplies, and the handoff becomes the biggest problem you have.

## Why this stopped working once AI arrived

The relay made sense once. Writing code, designing, testing: each took years to learn, no one could do it all, so the work was divided among different people.

Today AI does most of the hands-on work. The hardest part of a job is no longer building it. It is **knowing exactly what to build.**

Keep the old division of labor, and you have put a messenger between the person who knows what to build and the AI. A middleman.

And in the age of AI, every pass costs more than it used to.

Handoffs used to be one person writing for another. Now everyone works through AI. I explain my idea to my Claude Code, and it writes the spec for me. Three sentences of intent become three pages, possibly including things I never said. I have to check it line by line before giving it to the engineer. He then has his Claude Code read those three pages and build from them, and it adds its own interpretation.

So one piece of work travels from person to AI to person to person to AI. With every pass the information is inflated once, distorted once, and may pick up one more AI hallucination. What comes out the far end is several layers removed from what was wanted at the start.

Many teams keep the division of labor and give everyone at every stage an AI. Each leg does get faster. The handoffs take just as long as before, and lose more than before. That was us at the start, which is why the AI was fast and the work was slow.

## The new way: carry the baton to the finish

We changed the rule to one sentence: **whoever starts it, owns it to the finish.**

In Chinese we call it 一棒到底: one baton, all the way. In English, think of it as running in owner mode.

Once a goal is agreed, it goes to one owner. That person, working with Claude Code, does as much of it as possible from start to finish: deciding what it should achieve, design, development, testing, until it is really in use and meets its original goal. The baton doesn't change hands.

Three points need spelling out.

**Five stages, and everyone can do all five.** We divide any piece of work into business, product, design, dev and test. A stage says what is being done, not who does it. With Claude Code, one person can carry all five. I am not an engineer by training; today, in the systems I own, the product, UI, development and testing are all done by me with Claude Code.

**Answer for the result, not the process.** The owner doesn't answer to upstream or hand off to downstream. The owner answers for one thing: did it get done in the end. All the thinking goes into getting it done.

**Stages overlap and loop, and that isn't rework.** When one person carries a goal, product doesn't finish before dev starts, and dev doesn't finish before testing starts. They advance in turns. Testing finds five problems; you go back and fix the code, or go back and change the product, and keep testing meanwhile. That is nothing like the old "something's missing, send it back to the previous person, wait."

Take our own case. When I built the team board (more on what that is below), product, UI and development moved forward together: I looked at the working pages and gave feedback, went back to change the plan and the UI, and development carried on the whole time. Nothing was "finished and passed along," and nobody waited on anybody. Within a day of the first release, the two boards went through more than ten further small versions between them. Every one was proposed by me, built by me with Claude Code, accepted by me and shipped by me.

Side by side:

| | Relay race | Owner mode |
|---|---|---|
| Will things get lost? | Everything must be written up before the handoff; hours go in and things still go missing | It stays in one head; nothing to write up, nothing to lose in transit |
| Will the information warp? | It passes between people and AIs; each pass inflates and distorts it | One layer only: me and my Claude Code |
| How soon do you learn what's missing? | When the next runner is halfway through and hits the wall | The moment you get there, and you fix it on the spot |
| How long does one fix take? | Back, fixed, forward again, with a queue each way: days | Go back and change it yourself while carrying on: minutes to hours |
| Where does your attention go? | Explaining your own leg | Getting the whole thing done |
| Testing | A big batch at the end, problems all piled up | Test as you build, by the person who knows the work best |
| Waiting | A queue at every leg | Mostly, you wait for no one |

## Speed is the point

We didn't drop the relay to make life easier. We dropped it to be fast.

You cannot work out, sitting in a chair, whether a feature is good or a design makes sense. The only reliable way is to build it as fast as you can and get feedback from the market and from users. Even using it yourself for a while tells you more than ten meetings.

Build it, use it, change it, build again. The faster that loop turns, the closer you get to a mature product, and the sooner you learn whether the goal you set was right in the first place.

So the pace we set ourselves: every product line ships at least one iteration a week, and each person's own small loop closes every one to three days. Get it running first; no grand projects. Plan tight and don't fear slipping. When something slips, look at why, and let it push the pace.

## One project, done both ways

Back to the growth system and its three parts: web app, execution layer, device-control foundation.

**What actually happened:** I finished the prototype, wrote the spec, and handed it to the engineer. He built all three parts and handed them back for testing. The link between the web app and the execution layer was lost in the handoff, and we found the hole only at the very end. "In use this week" slid back one week at a time.

**How it would go in owner mode:** split it into three blocks, each with one owner who takes it from product through test.

- Web app: mine, start to finish.
- Execution layer: also mine, start to finish.
- Device-control foundation: the engineer owns the whole block. What it becomes and how it's built are his call.

Two things follow.

First, the web app and the execution layer sit in one pair of hands. Building the web side, I already know what the execution side must report back. The link between them doesn't have to be explained to anyone, so it can't get lost.

Second, it is plain who waits on whom. Execution-layer development waits on the foundation; the web app waits on nothing. So the owner of the foundation settles what its interface looks like as early as he can, and while I wait, I finish the web app and think the execution layer through. Nobody idles, and nothing falls between two people.

## A dozen terminals and one head: the personal board

Once the baton stays in one hand, the handoff trouble goes away and a new trouble arrives: **Claude Code is too fast for a person to keep up with.**

In a day, one person opens a dozen Claude Code terminals. One is building a page, one is fixing an API, another is running tests. And a single goal often takes more than one terminal: several at once, or one after another. With that many terminals open, you lose the thread. By evening you can't say where anything stands.

So we built our first tool: the **personal board**. It is for you and your Claude Code.

- **Every terminal files itself under a goal and a stage when it starts.** Claude Code says one line first, "I'm logging this terminal under such-and-such goal, dev stage," and unless you object, it's recorded. You fill in nothing. However many terminals a goal takes, they all land on the same row of the board.
- **It records only visible results.** A page works, a document is final, a test round is done. Open the board and you see where each thing stands and what comes next.
- **Entering a new stage for the first time needs your yes.** If the plan isn't settled and you're about to have it write code, it first lists what's missing and asks whether to go ahead. Claude Code runs fast, but for the step from "figured out" to "start building," you hold the wheel. Going back to fix what testing finds needs no permission. That's normal iteration.
- **Each goal carries one line: "next step."** No priority levels. You decide what to do first.

Since I started using it, I open the board every morning and know where yesterday's dozen terminals left each thing, and where to pick up today.

## Owner mode is not working alone

This way of working is easy to mistake for "everyone does their own thing." It isn't. People still work together; what changes is where. Before, one piece of work passed through several hands. Now a big goal is split into blocks, and each block has one person who owns it to the finish.

An example from what we're doing right now. Our app is getting a new feature that touches the app itself, the backend and the admin console. I started it. I worked out what it should achieve, then split it in two: the backend and third-party integration went to the backend engineer; everything inside the app, from product and UI to development and testing, went to the person who owns the app's product. Each owns their block outright.

A few rules apply.

1. **Align first, then commit.** A small team has limited energy; what to do and what to do first get decided together. Whether to do something is talked through at the weekly meeting or in conversation. Only once it's decided does it become a goal.
2. **I only did the opening, and the goal is still mine.** Each block has an owner who answers for that block. Whether the whole thing meets its goal in the end is still on me.
3. **Hand over a whole block, and the how belongs to its owner.** My examples are references, not instructions. What to do, how to split it, whether to bring in help: all their call.
4. **Owning it to the finish doesn't mean doing every step yourself.** Parts you can't do, someone else can. But what comes back, the owner must be able to accept. That step can't be skipped.
5. **For someone new to this, agree in advance where to pause.** This one isn't always needed. Only when the person taking a block is owning something end to end for the first time do we agree on a few stops along the way: when the product plan is done, I look once; when the UI is done, I look again. A look is a review, not a handoff. After it we decide the next step, so no one is pushed into a stage they aren't ready for. Once they've found their feet, the pauses go away and only the final acceptance remains.
6. **If you ask for help, you do the teaching.** When others join in on development or testing, the owner makes the standard clear and makes sure they learn it.
7. **Each stage is backstopped by the person whose craft it is.** Owner mode doesn't mean expertise stopped mattering. Everyone on a team came in with a specialty: one from product, one from engineering, one from design and testing. Here, whoever's specialty a stage is backstops that stage. On our team, business and product are mine to backstop; development, backend and production servers belong to our engineer; UI and testing belong to the colleague whose craft that is. If you get unsure in a stage, you ask its backstop or pull them in to work alongside you; if you truly get stuck, they catch it. A backstop is insurance. It doesn't mean the stage is theirs by default.

## No handoffs, so how does anyone know what's happening? The team board

That was the second new trouble. Handoffs used to tell everyone where things stood, as a side effect. Without them, how does anyone know who owns what, how far along it is, and what's stuck?

Hence our second tool: the **team board**. It is for people and people.

- **Every goal on one timeline.** Who owns each goal, how it's split, how long each stage took, where it's stuck: all at a glance. The new-feature example above is one row on the team board with two blocks under it, each showing its owner.
- **Who is waiting on whom is flagged ahead of time.** When one block needs another to finish first, and the block being waited on is due later than the date it's needed, the board warns early. No meeting required.
- **It's a map for everyone, not a ranking.** Anyone can see what the company is pushing forward and where their own block sits in the whole.
- **Say it; don't fill in forms.** To start something new or report progress, you describe it in your own words and let Claude Code record it on the board. If something is missing, it asks. We want everyone to think like a partner in the business, and laying a piece of work out clearly in words is that kind of thinking. Filling in forms is mechanical; it makes you think like an employee.

The two boards are separate. The personal board goes down to the hour and the terminal, and is for your eyes only. On the team board each goal is a one-line summary. At the end of the day you type "wrap up" in the terminal; Claude Code lists what the team should know from today, and only when you say yes does it go to the team board.

## What it costs

The costs should be said plainly.

When people who aren't trained engineers build with Claude Code, the code may not be pretty. We accept that risk. At this stage, something that runs and can be validated matters more than a handsome architecture.

Also, keep a trail even when you work alone. Even if one person does everything, the start and end of every stage still gets recorded, so that when you look back you can see where the time went. The personal board takes care of that; you don't have to.

## Who it's for

It fits small teams where everyone works with tools like Claude Code and is willing to own a result to the finish. It also fits a solo developer with a screenful of terminals; the personal board alone is enough.

It fits less well where strict separation of duties and sign-offs are required, or where people aren't yet willing to step outside their old stage. This way of working asks everyone to walk a few steps further than they used to.

## Open source

Both boards and the skills that go with them are open source, in a project called Baton (一棒到底):

- **Personal board:** download it and it runs on your own machine; connect Claude Code and you're set.
- **Team board:** try it locally, or host it on your team's own server.
- **Skills:** they teach Claude Code how to work with you this way: when to record, and when it must ask you first.
- **Demo data:** a complete board for a fictional team, plus the real record of these two boards going from idea to launch, which you can open and read entry by entry.

Repository: github.com/kezhentong-arch/baton
Video: coming soon

One goal. One owner. Claude Code. All the way to the finish.
