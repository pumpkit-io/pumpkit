# Versions are written in the background by sketches, a merge and a humanizer

A Version used to be written inside the request by one sketch call and one humanizer call. A Brief can now start several Posts at once (ADR 0025), and each Post takes more model calls, so a request can no longer wait for the writing. Pumpkit writes every Version in an in-process background task, the User's page polls for it, and a write that never finishes turns into a failure the User can retry.

## The pipeline

- The first Version of a Post runs: five sketch calls in parallel, each asked to try a different hook type first, then the merge, the scrub, the humanizer and the scrub again. A sketch call that fails is skipped as long as one succeeds.
- The merged sketch after the scrub is the Version's Sketch. The Version also keeps the hook levers, hook types and CTA type the writing chose, in place of a hook library name, and the sketches, the merge's reviews and reasoning and each step's model and usage. Those are never shown: they are there to diagnose a bad Post.
- Feedback writes a Version with a revise call and a humanizer. Its conversation replays the Post's Versions, as ADR 0016 says, and never the sketches or the merge.
- A post and a Thread never share a prompt. Each step has one prompt for a post and one for a Thread, assembled from shared sections.
- Each step's model is a setting with a working default. The sketch count, the cap on Ideas and the hook-type rotation are constants in code, because the prompts are tuned against them.

## The background task

- The request that starts writing checks the attempt limit and the Generations left for every Idea asked for, creates each Post in a writing state, starts the task and returns.
- A Post in its writing state before its first Version is not a Draft. It appears only on its Brief's page.
- The Posts of one Brief are written in parallel. One Instance-wide setting caps the model calls in flight, 8 by default, so a burst of Briefs doesn't trip the provider's rate limits.
- One Generation is charged per Post when its first Version succeeds, and one per Feedback. A failed write is free. Each Post written counts toward the existing hourly attempt limit.
- Feedback runs through the same task and the same polling, so writing has one way to run.

## The timeout rule

The task lives in the backend process and nothing else records that it is running, so a restart loses the writes in flight. Pumpkit therefore reports a Post whose writing state is older than a timeout as failed, with Retry. Retry reuses the Idea's Plan and counts as a new attempt. The Ticket that builds background writing sets the timeout.

## Consequences

- ADR 0013 chose Jev partly because Versions were written inside the request. That premise no longer holds. Its rule that Jev classifies and LLMs write is unchanged.
- A failed or lost write costs the User a retry and no Generation.
- Tests await the task through the application's task registry, or run it inline, and need no worker.

## Considered Options

- **Keep writing inside the request.** Five Posts from one Brief would take five times as long behind one response, and the User couldn't leave the page while they are written.
- **A durable job queue, or a worker process as the publisher has (ADR 0007).** It would survive a restart. We left it out because a write lost to a restart is recoverable without one: the Plan is stored, a failed write is free, and the timeout rule shows the failure with Retry.
