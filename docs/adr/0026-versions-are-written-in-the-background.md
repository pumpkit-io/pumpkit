# Versions are written in the background by sketches, a merge and a humanizer

A Version used to be written inside the request by one sketch call and one humanizer call. A Brief can now start several Posts at once (ADR 0025), and each Post takes more model calls, so a request can no longer wait for the writing. Pumpkit writes every Version in an in-process background task, the User's page polls for it, and a write that never finishes is shown as a Post Pumpkit couldn't write, which the User can retry.

This amends ADR 0013, ADR 0015 and ADR 0017, as the sections below say. Their other decisions continue to apply.

## The pipeline

- The first Version of a Post runs: five sketch calls in parallel, each asked to try a different hook type first, then the merge, the scrub, the humanizer and the scrub again. A sketch call that fails is skipped as long as one succeeds.
- The five candidates are sketches, in lowercase. The Sketch of the glossary is the one text the merge makes of them, after the scrub. The Version also keeps the hook levers, hook types and CTA type the writing chose, in place of a hook library name, and the sketches, the merge's reviews and reasoning and each step's model and usage. Those are never shown: they are there to diagnose a bad Post.
- Feedback writes a Version with a revise call and a humanizer. Its conversation replays the Post's Versions and Feedback, and never the sketches or the merge.
- A single X post and a Thread never share a prompt. Each step has one prompt per Format, assembled from shared sections.
- Each step's model is a setting with a working default. The sketch count, the cap on Ideas and the hook-type rotation are constants in code, because the prompts are tuned against them.

## The background task

- The request that starts writing checks the hourly attempt limit and the Generations left for every Idea asked for, creates each Post in its writing state, starts the task and returns.
- The Posts of one Brief are written in parallel. One Instance-wide setting caps the model calls in flight, 8 by default, so a burst of Briefs doesn't trip the provider's rate limits.
- One Generation is charged per Post when its first Version succeeds, and one per Feedback. A write that produces no Version is free. Each Post written counts toward the hourly attempt limit, which exists already.
- Feedback runs through the same task and the same polling, so writing has one way to run.

## The writing state and ADR 0015's statuses

ADR 0015 gives a Post four statuses, each taken from its Scheduled post or the lack of one: Draft, Scheduled, Published and Failed. A Post waiting for its first Version has none of them. It is in its writing state: Pumpkit is writing it, or couldn't write it and offers Retry. Such a Post is not a Draft and appears only on its Brief's page, so it sits in none of the Posts tabs. It becomes a Draft when its first Version is written.

A write that produces no Version is never called Failed. Failed stays the status of a Scheduled post Pumpkit gave up publishing.

A Post that Feedback is rewriting keeps its status while the next Version is written.

## The timeout rule

The task lives in the backend process and nothing else records that it is running, so a restart loses the writes in flight. Pumpkit therefore treats a Post whose writing state is older than a timeout as one it couldn't write, and shows it with Retry. Retry reuses the Idea's Plan and counts toward the hourly attempt limit again.

The timeout is 15 minutes (`WRITING_TIMEOUT`) for the first Version, and for Feedback once #481 writes it in the background. Until then Feedback keeps its 30-minute hold (`FEEDBACK_WRITING_TIMEOUT`), because it still runs in the request and a late Feedback would record over an edit made after the shorter hold ended. A write is three steps whose model calls each time out at 240 seconds once they hold a slot under the in-flight cap, plus the wait for a slot; real writes take about 40 seconds. A write that ends after its Post was retried records nothing, so a Post never gets two first Versions or two charges.

This holds because the backend runs as one process: `backend/start.sh` starts one uvicorn worker, and the tasks and the in-flight cap live in that process. Running several workers or replicas would keep every write working, since each task records its own outcome in the database, but each process would have its own cap on model calls in flight.

Writes in flight count toward the hourly attempt limit from when they started, and each holds one Generation until it ends or outlives its timeout, so a User can't start more writes than they have Generations left.

## Consequences

- ADR 0013 chose Jev partly because Versions were written inside the request. That premise no longer holds. Its rule that Jev classifies and LLMs write is unchanged.
- ADR 0017 set the Allowance and the Top-up from what a Generation cost in model calls under the earlier pipeline. A Post's first Version now takes five sketch calls, a merge and a humanizer, and this ADR does not estimate the new cost.

## Considered Options

- **Keep writing inside the request.** Five Posts from one Brief would take five times as long behind one response, and the User couldn't leave the page while they are written.
- **A durable job queue, or a worker process as the publisher has (ADR 0007).** It would survive a restart. We left it out because a write lost to a restart is recoverable without one: the Plan is stored, the User was charged nothing, and the timeout rule shows the Post with Retry.
