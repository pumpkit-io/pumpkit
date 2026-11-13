# One Brief plans one or more Posts, each with a Plan

A Brief often holds several ideas. A User who dictated five lessons got one Post that picked one lesson or crammed all five in, and had to split the Brief by hand to get the others. Pumpkit now plans a Brief before writing it: it finds the Ideas worth posting, gives each a Plan, and writes one Post per Idea the User picks. The Brief becomes a record of its own, and a Post belongs to one Idea of one Brief.

This amends ADR 0016's premise of one Brief per Post, and ADR 0012 for the tools. Their other decisions continue to apply.

## The model

- A **Brief** belongs to one User and holds the text the User wrote, the Positioning it was planned with (ADR 0024), the planner's reasoning and its Ideas.
- An **Idea** is one Post the planner proposes for a Brief. Every Brief has a single-post Idea, which covers the whole Brief, and a Brief that holds clearly separate ideas also has two to five split Ideas in posting order. Every Idea is kept, written or not, so the User can write one later without planning again. An Idea has at most one Post.
- A **Plan** is what the planner decided for an Idea: core idea, takeaway, reasoning, funnel stage (top, middle or bottom), desired action, Format, Length (short, medium or long, and none for a Thread) and structure.
- A **Post** links to its Idea and through it to its Brief. It no longer stores the Brief's text.

## Planning

- Planning a Brief is one model call inside the request. It gets the Brief, the User's Positioning and the account's character limit, and returns the planner's reasoning, the single-post Idea and, when the Brief holds clearly separate ideas, the split Ideas.
- The planner chooses the Format. The User no longer picks it when starting a Post, and an explicit ask in the Brief ("as a thread", "write one post about this") is followed. The planner chooses a Thread when the material needs more room than the account's limit allows, and prefers a medium or long post on an account with a longer limit.
- In the web app, a Brief with no split Ideas starts writing its single-post Idea in the planning request, so the simple case stays one step for the User. With split Ideas, the User picks which to write, or asks for one Post covering everything, which writes the single-post Idea.
- Planning is never a Generation. One Generation is charged per Post written (ADR 0026), and that includes the Post a planning request starts when there are no split Ideas.
- Planning is rate limited by the existing per-minute write rate and a per-User hourly cap, whose number #472 sets.
- Choices in a Plan that pull against each other are logged, and the Post is still written.
- The User can't change a Plan before writing. Feedback overrides it afterwards ("make it longer", "no CTA", "turn it into a thread").

## What ADR 0016 keeps and what changes

Each Idea's Post is an ordinary Post: one Text, an append-only History, Feedback on the Text as it is, and at most one Scheduled post (ADR 0015). What changes is where the first Version comes from: the Post's Idea and its Brief, which several Posts may share. Feedback is revised against the Positioning the Brief kept, not the User's current one.

A User may discard a Draft. That deletes the Post and its Versions for good, the one case where Versions are removed, and it is refused on a Scheduled or Published Post. A discarded Post's Generation is not refunded.

No data is migrated, because no Instance has real Users. A Post written before this change has no Plan and is refused Feedback, with a message saying so.

## MCP tools (amends ADR 0012)

- `plan_posts` takes a Brief and returns it with its Ideas and their Plans, the single-post Idea included. It starts nothing, even when there are no split Ideas.
- `write_posts` starts writing the Ideas the AI app names, split Ideas or the single-post Idea, and returns the Post ids. `get_post` reports whether a Post is still being written.
- `delete_post` deletes a Draft.
- `get_positioning` and `set_positioning` live in the `positioning` area's tools.
- `start_post` and the three Inspiration author tools are removed. `give_feedback` keeps its shape.
- The server instructions describe Positioning and the two steps, and tell the AI app to show the Ideas and ask the User which to write.

The web API's create-Post endpoint is removed as well, and planning a Brief and writing its Ideas take its place. It differs from the tools in one way: its planning request starts the single-post Idea when there are no split Ideas, where an AI app always calls `write_posts`.

## Considered Options

- **Keep one Post per Brief.** The User keeps splitting Briefs by hand, and the writing keeps choosing between dropping ideas and cramming them in.
- **Write every Idea the planner finds.** A User would spend Generations on Ideas they don't want. Planning costs no Generation, so they are charged only for Posts they asked for.
- **One tool, as `start_post` was.** An AI app would have no point at which to show the Ideas, so the User couldn't choose in the conversation.
- **Let the User edit a Plan before writing.** Feedback already changes any choice in a Plan, after the User has read the Post.
