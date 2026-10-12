# A separate publisher process publishes Scheduled posts at most once

A publisher process, run from the backend image as its own `publisher` compose service, polls Postgres about every 30 seconds for due Scheduled posts and claims each with `SELECT ... FOR UPDATE SKIP LOCKED`. It starts only once the backend is healthy, so it never runs against an unmigrated database. The API runs as a single uvicorn worker today, but a loop inside it would stop whenever the API restarts and would run twice the moment a second worker is added. A job queue would add Redis for a load one polling loop handles. A Scheduled post can go out up to about 30 seconds late, which is accepted at minute precision. "Post now" doesn't wait for the publisher: the API request claims and publishes the new Scheduled post itself, through the same code and the same lock.

Pumpkit marks a Scheduled post as publishing before it calls X, and never calls X twice for it unless X clearly did not publish it (a 429, or a refused connection). A timeout or a 5xx may hide a post X did accept, so it makes the Scheduled post Failed with a reason telling the User to check their X profile. A duplicate on the User's own X account is worse than a missed one, so don't add blind retries.

## Considered Options

- **Loop inside the API process, guarded by a Postgres advisory lock.** No extra service, but deploys and API restarts would interrupt publishing.
- **Job queue (arq or Celery) with Redis.** Exact-time jobs, but a new piece of infrastructure to run and back up.
