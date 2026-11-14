# Media is published content the writing never sees, kept by the Instance until it goes out

Users can attach Media (images, an animated GIF or a video) to a Post's Text, and Pumpkit publishes it inside the X post, through X's media upload and `media.media_ids` on `POST /2/tweets`. Media belongs to the Text, never to a Version, and Pumpkit's writing never receives it: no bytes, no file names, no alt text. Reading media costs far more than reading text, and the Operator pays for every Generation. A User who wants an AI to look at an image and write from it uses their own AI app through the MCP server, which attaches the Media and starts the Post from a text Brief.

X keeps an uploaded media id for only about 24 hours, so a Scheduled post can't hold X's ids. The Instance keeps each file itself, on a disk volume shared by the backend and the publisher, behind a storage interface, and uploads it to X just before the X post that carries it is published. Once that X post is Published, the file is deleted and only a small preview stays.

## Considered Options

- **Let the writing see the Media.** Better-matched text, but every Generation with an image or video would cost several times more, on the Operator's account.
- **Files in Postgres.** No new volume, but wrong for video of hundreds of MB.
- **S3-compatible object storage.** Scales and keeps the servers stateless, but every Self-hoster would need a bucket and keys. The storage interface leaves room to add it later as an optional provider (ADR 0011).
- **Upload to X when scheduling.** Simpler publishing, but ids expire long before most publish times.

## Consequences

- X connections ask for `media.write` along with every other scope, so a User grants everything once (ADR 0006). A connection made before this ADR is asked to reconnect only when its User attaches Media.
- A failed media upload means X published nothing, so it retries like a 429, and a lasting refusal makes the Scheduled post Failed with X's reason. The retry window counts only the waits between attempts (1, 2, 4 and 8 minutes), not the time an attempt takes, for every Scheduled post: a video upload can run for an hour, and it must not use up the window before X's first refusal. ADR 0007's at-most-once rule for `POST /2/tweets` is unchanged.
- The publisher runs a few publishes side by side (4 today), each claimed on its own, so one video uploading for an hour doesn't hold up every other due Scheduled post. A bound keeps the load on the Instance and on X small, at a cost: a due Scheduled post waits while that many publishes are under way, so behind as many long uploads it can go out an hour or more late (amends ADR 0007). Two due Scheduled posts of one User can publish side by side too, so they may land on X out of `publish_at` order.
- Post now with a GIF or a video hands the Scheduled post to the publisher, due now, instead of publishing inside the request (amends ADR 0007). Unlike an image, X processes a GIF or a video after its upload. A video's upload and that wait together can outlast the request and the proxy's response timeout. The Post shows "Posting…" until it is Published or Failed. Post now with images still publishes inside the request.
- Media nothing references any more (removed or replaced) is deleted with its files by the publisher's pass, an hour after it was created at the earliest. A discarded Draft's Media is deleted with it at once (ADR 0025). A Published Post's Media keeps its record and preview while its Scheduled post references it.
- Self-hosters get a new volume to keep and back up, announced in the Release's Upgrade notes.
- Attaching Media uses no Generation and no X post of the Allowance.
