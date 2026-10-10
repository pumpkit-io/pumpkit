# Publish through the official X API; keep twitterapi.io for reads

Scheduled posts are published with the official X API (`POST /2/tweets`), on behalf of the User, through an X connection made with X's OAuth 2.0 PKCE flow and the scopes `tweet.read tweet.write users.read offline.access`. twitterapi.io cannot publish on a User's behalf, and publishing through anything X does not sanction would put Users' own accounts at risk, so ADR 0005's trade-off does not carry over: reads stay on twitterapi.io, writes go to X. An X connection only grants Pumpkit permission to publish; it never signs anyone in, so ADR 0002 still holds and X stays out of the Sign-in methods.

## Consequences

- Pumpkit holds a refresh token per X connection, encrypted at rest, and rotates it on every refresh. Only one process may refresh a given X connection at a time, because X invalidates the old refresh token.
- Pumpkit's X developer app pays for every publish, so each User has a monthly cap on Scheduled posts.
- Pumpkit now depends on two X providers: twitterapi.io for Inspiration authors and the X API for publishing.
