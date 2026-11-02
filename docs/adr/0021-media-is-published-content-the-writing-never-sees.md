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
- A failed media upload means X published nothing, so it retries like a 429 within the existing retry window, and a lasting refusal makes the Scheduled post Failed with X's reason. ADR 0007's at-most-once rule for `POST /2/tweets` is unchanged.
- Post now with a video hands the Scheduled post to the publisher instead of publishing inside the request, because uploading and processing a video can outlast the request (amends ADR 0007). Post now with images still publishes inside the request.
- Self-hosters get a new volume to keep and back up, announced in the Release's Upgrade notes.
- Attaching Media uses no Generation and no X post of the Allowance.
