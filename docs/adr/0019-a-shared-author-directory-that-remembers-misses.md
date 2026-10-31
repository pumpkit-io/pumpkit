# A shared Author directory that remembers misses

Every twitterapi.io call costs the Operator money, so the X accounts an Instance learns about go into one Author directory shared by all its Users, and nothing is ever removed from it. It starts from a seeded list of handles, names and photos, and grows each time a User looks a handle up on X and finds it. A lookup uses the profile endpoint, about one fifteenth the cost of fetching posts; posts are fetched only when the account is added to a Persona, and posts up to 7 days old are reused across Users. A lookup that finds nothing is remembered for every User: 7 days for a handle that doesn't exist or is suspended, 1 day for a protected account. Each User may run 10 lookups an hour and 30 a day, under one Instance-wide daily cap. Directory picks and remembered misses don't count towards either. All of these numbers are configurable. This extends ADR 0005: twitterapi.io stays the only way Pumpkit reads X.

Search runs in the browser over the whole directory, with fuzzy matching on handle and name and a minimum score. A query starting with `@` means exactly that handle and puts "Look up on X" first. Without the `@`, directory matches come first, so typing a name never spends a lookup on a stranger who owns that word as a handle.

## Considered Options

- **Per-User author lists with no shared record.** Every User would pay for the same lookups again, and the picker would have nothing to suggest.
- **Search on the server with Postgres trigrams.** It needs a round trip per keystroke, and SQLite, which the tests run on, can't do it. The directory is a few thousand rows at most for now.
- **Look up on X whenever a query isn't an exact directory handle.** A User typing "pieter" for Pieter Levels would pay for, and might add, @pieter.
