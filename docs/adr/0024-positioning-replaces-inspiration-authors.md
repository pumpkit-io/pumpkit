# Positioning replaces Inspiration authors, which stay in the code inactive

A User's Persona is their Positioning: one free text saying who they are on X, what they post about, who they write for, what they post for and what they can point readers to. Until now the Persona was up to three Inspiration authors, whose recent posts set the writing style of the User's Posts. Copying the style of other accounts told the writing nothing about who the User is, who reads them, or whether a Post should earn reach, trust or a sign-up, so every Post got the same treatment whatever its material. The writing now plans every Post around the Positioning, and no Inspiration author's posts reach it.

This amends ADR 0018 and ADR 0019, extends ADR 0008's area order, and takes ADR 0012's Inspiration author tools off the MCP server. The other decisions of ADR 0018, ADR 0008 and ADR 0012 continue to apply. ADR 0019's decisions now describe code that stays in the repository and that no User can reach.

## Positioning

- A User has at most one Positioning. It is one free text, with no guided fields.
- Pumpkit drafts it and the User edits it. The draft reads the bio, location and website X gives at sign-in at no cost, and the User's newest posts, about 20, through the X reader in one paid call (ADR 0005). It runs when Onboarding's Persona step first opens, so the Operator pays twitterapi.io only for a User who is past the Paywall.
- The draft states only what the profile and posts show, leaves out what they don't, and copies no post's wording. It is one model call on its own setting, `LLM_POSITIONING_MODEL`.
- The X connection keeps the bio, location and website from every read of the X account, not only sign-in's, so a reconnect or a publish refreshes them instead of erasing them.
- A failed X read or model call gives no draft and no error page: the request answers with the reason in words for the User, who starts from an empty Positioning or keeps the text they had.
- A draft is not a Generation, and requesting one saves nothing: a redraft on the Persona page leaves the saved Positioning alone until the User saves. A User gets 5 drafts in any 24 hours, the first draft of Onboarding included. A request counts once it goes on to read X, whatever X and the model then answer, because the Operator pays for that read. At the limit the Persona page disables the redraft button and says "You can draft again tomorrow." A Positioning must not be blank once the space around it is trimmed; it has no minimum length and holds at most 4,000 characters.
- A Brief keeps the Positioning it was planned with (ADR 0025), so editing the Positioning later doesn't change how Feedback on older Posts behaves.
- A User with no Positioning can't plan a Brief and is pointed at the Persona page. This replaces the check that refused a Post when the User had no Inspiration author's posts to write from.

## Onboarding (amends ADR 0018)

Onboarding's Persona step asks for a Positioning in place of an Inspiration author. ADR 0018's rule is unchanged: a step is done when what it asks for exists, so the step is done once a Positioning is saved, and a User who finished Onboarding is never sent back.

## Inspiration authors are inactive (amends ADR 0019)

This follows ADR 0023's mechanism for Google and Magic link. The code listed here stays in the repository, and nothing a User or an AI app can reach runs it:

- The author routes move to a router the application never mounts.
- The three Inspiration author MCP tools leave the server's tool list.
- The Persona page's author panel, the picker and their provider stay in the frontend with nothing rendering them.
- The Author directory, the corpus module, the old sketch and thread prompts and the hook library stay in the backend with no caller the application mounts.
- There is no configuration switch. Someone who wants Inspiration authors back changes the code.
- All of it keeps its tests, which mount their own assembly. One test asserts that the application mounts none of those routes or tools.

The X reader is not on that list. It stays in use: the Positioning draft reads the User's posts through it, by way of the `authors` area's service, and Community lookups call it as before.

The Author directory of ADR 0019 therefore stops growing: no User can look a handle up or pick from it. Its lookups, limits and search stay in the code with their tests, inactive like the rest. ADR 0005 still holds: twitterapi.io stays the only way Pumpkit reads X, and an Instance still needs its key, now for the Positioning draft and Communities.

## Where Positioning lives (extends ADR 0008)

Positioning gets its own backend area, `positioning`, with a router, mediator, service, schemas, models and MCP tools. In the area order it sits above `authors`, whose service it calls to read the User's posts, and below `posts` and `onboarding`, which read the Positioning to plan a Brief and to tell whether the Persona step is done. ADR 0008's written order predates `onboarding`: the order in force is the layers contract in `backend/pyproject.toml`, where `onboarding` shares the layer of `posts`. The draft goes through the LLM port, which moves from `posts` to `core` (`core/llm.py`, with its client and schemas): `positioning` sits below `posts` and can't import it, and the port now has two areas calling it, as the classifier port does (ADR 0013).

## Considered Options

- **Keep Inspiration authors as the Persona and add Positioning beside them.** The writing would have to serve a style corpus and a Positioning at once, and a User would have to choose between them. The new prompts have no place for a corpus.
- **Delete the Inspiration author code.** Keeping it with passing tests lets someone adapt it later, as ADR 0023 did for Google and Magic link.
- **A configuration switch for Inspiration authors.** ADR 0023 refused one for the inactive Sign-in methods, and the same holds here: the code being present must not imply that Inspiration authors can be turned on.
- **Positioning in the `onboarding` area.** Positioning outlives Onboarding: the Persona page edits it and every Brief is planned with it. `posts` would also have to import `onboarding`, which sits beside it in the area order.
