# Read X posts through twitterapi.io, not the X API

Pumpkit reads Inspiration authors' recent posts from twitterapi.io, a third-party scraper API, instead of the official X API. Each author costs one request for about twenty original posts, and the X API's read pricing is much higher for the same data. The pumpkit-v6 experiments already used it to fetch the posts their prompts were tuned on. In exchange, Pumpkit depends on a provider X does not sanction, which can break or change without notice, and it needs a `TWITTERAPI_IO_API_KEY` beside the OpenRouter key.

## Considered Options

- **Official X API.** Sanctioned and stable, but costs far more per post read.
- **The User pastes sample posts.** No provider at all, but each User has to curate the samples by hand, and the style would come from whatever the User happened to copy.
