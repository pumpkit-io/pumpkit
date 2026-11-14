# One Brief plans one or more Posts, each with a Plan

A Brief often holds material for several Posts. A User who dictated five lessons got one Post that picked one lesson or crammed all five in, and had to split the Brief by hand to get the others. Pumpkit now plans a Brief before writing it: it finds the Ideas worth posting, gives each a Plan, and writes one Post per Idea the User picks. The Brief becomes a record of its own, and a Post belongs to one Idea of one Brief.

This amends ADR 0016's premise of one Brief per Post, and ADR 0012 for the tools. Their other decisions continue to apply.

## The model

- A **Brief** belongs to one User and holds the text the User wrote, the Positioning it was planned with (ADR 0024), the planner's reasoning and its Ideas.
- An **Idea** is one Post the planner proposes for a Brief. Every Brief has a single-post Idea, which covers the whole Brief, and a Brief whose material clearly separates into several Posts also has two to five split Ideas in posting order. Every Idea is kept, written or not, so the User can write one later without planning again. An Idea has at most one Post.
- A **Plan** is what the planner decided for an Idea: core idea, takeaway, reasoning, funnel stage (top, middle or bottom), desired action, Format, Length (short, medium or long, and none for a Thread) and structure.
- A **Post** links to its Idea and through it to its Brief. It no longer stores the Brief's text.

## Planning

- Planning a Brief is one model call inside the request. It gets the Brief, the User's Positioning and the account's character limit, and returns the planner's reasoning, the single-post Idea and, when the Brief's material clearly separates, the split Ideas.
- The planner chooses the Format. The User no longer picks it when starting a Post, and an explicit ask in the Brief ("as a thread", "write one post about this") is followed. The planner chooses a Thread when the material needs more room than the account's limit allows, and prefers a medium or long post on an account with a longer limit.
- In the web app, a Brief with no split Ideas starts writing its single-post Idea in the planning request, so the simple case stays one step for the User. With split Ideas, the User picks which to write, or asks for one Post covering everything, which writes the single-post Idea. The two are exclusive: a request naming the single-post Idea with split Ideas is refused, since it would write the whole Brief and a part of it.
- Planning is never a Generation. One Generation is charged per Post written (ADR 0026), and that includes the Post a planning request starts when there are no split Ideas.
- Planning is rate limited by the existing per-minute write rate and a per-User cap of 20 plan calls an hour (`PLAN_CALLS_PER_HOUR`). Every plan call counts, a failed one included, since a failed call is paid for too. A planning request is also refused up front at the hourly attempt limit, since a Brief with no split Ideas starts writing its Post at once.
- A User with no Generations left can still plan, so they see a split Brief's Ideas and can untick some or top up. The ideas step shows the cost against the Generations left, with a top-up link, and the planning answer carries that count as the server checks it, writes in progress taken out. A Brief with no split Ideas planned without room is stored with its single-post Idea unwritten, and New post shows it the same way. The attempt limit and the Generations left are checked again after the plan call, under the User's lock, since other requests may have used the room meanwhile; when they fail then, the Brief is kept unwritten too. `start_post` still refuses a User with no Generation left before the plan call, and refuses after it when the room ran out meanwhile.
- Choices in a Plan that pull against each other are logged, and the Post is still written.
- The User can't change a Plan before writing. Feedback overrides it afterwards ("make it longer", "no CTA", "turn it into a thread").

## A Post's place among its Brief's Posts

A Brief's Posts are the Posts of its Ideas, in the order of those Ideas: the single-post Idea's Post first, then the split Ideas' Posts in posting order. A Post written, being written or not written counts, since each opens on its page and sits on the Brief's page. An Idea with no Post doesn't count, and a discarded Post leaves the count. A Brief can hold the single-post Idea's Post next to split Posts once the User writes both in two requests; the one covering the whole Brief comes first. So a card's number on the Brief's page and "2 of 4" on a Post's page and a Draft's row give the same place, and previous and next step through all of those Posts. The Brief's page header counts something else: progress over those Posts and the Ideas still offered (see [The Brief's page](#the-briefs-page)). A Post that is its Brief's only one shows no place.

## What ADR 0016 keeps and what changes

Each Idea's Post is an ordinary Post: one Text, an append-only History, Feedback on the Text as it is, and at most one Scheduled post (ADR 0015). What changes is where the first Version comes from: the Post's Idea and its Brief, which several Posts may share. Feedback revises the Text against the Positioning the Brief kept, not the User's current one.

Only a Draft can be discarded. Discarding deletes the Post and its Versions for good, the one case where Versions are removed. Every other Post is refused: a Scheduled, Published or Failed one, and a Post still waiting for its first Version. A discarded Post's Generation is not refunded.

A Post written before this change gets a Brief and an Idea of its own, so every Post belongs to an Idea. It gets no Plan, so it is refused Feedback, with a message saying so.

## The Brief's page

The Brief's page shows a card for each of the Brief's Posts, written, being written or not written, in the Brief's order: the single-post Idea's Post first, then the split Ideas' Posts in posting order. A card's number is its place among those Posts, not its Idea's posting order, so writing the first and third Ideas gives cards 1 and 2. The header reads "n of m written", where n counts those Posts and m adds the Ideas the page offers under "Not written".

The single-post Idea and the split Ideas are alternatives, so "Not written" offers only the kind that already has a Post. When both kinds have one, which takes two requests, it offers the split Ideas left. While no Idea has a Post, it offers every split Idea in posting order and then the single-post one, labelled "One post covering everything", so a Brief left unwritten for want of Generations can be written from the page.

A Brief with one Post and no Idea left to offer never shows the page: it opens that Post's page, also right after "Write this one" writes a one-idea Brief.

## Recent briefs on New post

New post lists the User's ten latest Briefs, newest by creation time first, so they can return to Posts still being written and to Briefs they planned but didn't write. Each row shows the start of the Brief's text and one label, read from the same counts as the Brief's page: the Brief's Posts by writing state, and the Ideas its page offers. The first that applies:

1. "Writing…" while any of its Posts is being written before its first Version, a Post the User hasn't seen yet.
2. "1 post couldn't be written" (or "n posts…") while any Post's first Version failed or was lost, since that Post waits for Retry.
3. "Not written yet" with no Post: a split Brief whose Ideas the User didn't pick, or a Brief stored unwritten for want of Generations.
4. "n of m written", the Brief page's header, while Ideas are still offered.
5. "n written" when nothing is offered.

A Post that Feedback is rewriting already has a Text the User has seen, so it counts as written, and New post doesn't read the list again for it. From the third case on, every Post counted is written, so the row and the page header agree wherever both show a count. A row opens the Brief's page, or its Post by the rule above when the Brief has one Post and nothing to offer. The section is left out while the User has no Brief. New post reads the list when it opens and again every ten seconds while any first Version is being written, more slowly than a Brief's page, since the list only signals that work is under way.

## MCP tools (amends ADR 0012)

- `plan_posts` takes a Brief and returns it with its Ideas and their Plans, the single-post Idea included. It starts nothing, even when there are no split Ideas.
- `write_posts` starts writing the Ideas the AI app names, split Ideas or the single-post Idea, and returns the Post ids. `get_post` reports whether a Post is still being written.
- `delete_post` discards a Draft, and refuses any other Post.
- `get_positioning` and `set_positioning` live in the `positioning` area's tools.
- `start_post` is removed. The three Inspiration author tools leave the server's tool list and stay in the code (ADR 0024). `give_feedback` keeps its arguments. Once Feedback is written in the background (ADR 0026), it answers that the Version is being written, and `get_post` reports when it is done.
- The server instructions describe Positioning and the two steps, and tell the AI app to show the Ideas and ask the User which to write.

The web API's create-Post endpoint is removed as well, and planning a Brief and writing its Ideas take its place. It differs from the tools in one way: its planning request starts the single-post Idea when there are no split Ideas, where an AI app always calls `write_posts`.

## Considered Options

- **Keep one Post per Brief.** The User keeps splitting Briefs by hand, and the writing keeps choosing between dropping part of the Brief and cramming all of it in.
- **Write every Idea the planner finds.** A User would spend Generations on Ideas they don't want. Planning costs no Generation, so they are charged only for Posts they asked for.
- **One tool, as `start_post` was.** An AI app would have no point at which to show the Ideas, so the User couldn't choose in the conversation.
- **Let the User edit a Plan before writing.** Feedback already changes any choice in a Plan, after the User has read the Post.
