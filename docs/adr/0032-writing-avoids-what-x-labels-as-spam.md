# Pumpkit's writing avoids what X labels as spam, and Reach warnings never block

X's open-source For You code (xai-org/x-algorithm) labels a post `SpamHighRecall` when its spam classifier finds engagement baiting, engagement farming or a request for shares, and a labelled post is hidden from everyone who doesn't follow its author. Small accounts, which most Users have, get no exemption from these labels. Pumpkit's writing guide, ported from pumpkit-new-architecture-v5, sometimes asked for exactly that: the share desired action could close on "Send this to a founder who…", and the top-of-funnel CTAs listed it as a good choice. So the writing now departs from v5. It never asks readers to share, tag, copy the link, like, repost, follow, or reply for a reward, and Pumpkit warns the User about what is left, in a Post's Text and in when it is scheduled, without stopping them.

This amends ADR 0026: a Post's first Version is written as v5 does, except for the rules below. Its other decisions continue to apply.

## Rules

- Every sketch, merge, humanizer and revise call is told which asks X labels as spam. The merge and the humanizers remove such an ask when a sketch writes one.
- A desired action stays a goal, and asking for it is a separate choice. Share and bookmark are earned by the post and never asked for. Follow gives what comes next as the reason and never says "follow".
- Hook examples name their topic, and none of them uses profanity or all-caps urgency. A curiosity gap with no topic is clickbait.
- The writing adds no @mention unless the Brief names the account and the post is about it, and never more than one.
- Feedback still wins. When a User asks for a forbidden ask, revise writes it.
- Reach warnings are worked out from the Text whenever it is read, and from a Scheduled post's text when it is scheduled, posted now or edited. They aren't stored. They cover asks X labels as spam, two or more @mentions or hashtags in one Part, link shorteners, and another of the User's Scheduled posts, waiting or Published, less than two hours from the chosen time.
- A Reach warning never refuses scheduling or Post now. Refusal stays for text that can't be published as it is, such as the `[link]` placeholder.
- Split Ideas from one Brief go out one a day: the web app's Schedule time defaults to the day after the Brief's latest Scheduled post, and the MCP server instructions tell AI apps the same.

## Considered Options

- **Keep v5's guide as it is.** It's tested writing, but it would keep asking for shares that X's code hides from non-followers.
- **Refuse to schedule a post with a spam ask.** It would protect reach, but the check is a regex with false positives, and the User's word wins everywhere else in Pumpkit, Feedback included.
- **Store the warnings with each Scheduled post** to measure which patterns lose reach. That is worth doing, but as its own feature, together with reading impressions back.
