# A First reply is the last Part of a single X post

Pumpkit's writing puts an external link in a First reply, a reply the User's account posts under its own post. #467 gives the reason: the post itself shouldn't be penalised for carrying the link. A First reply is stored as the last Part of a single X post's Text. The Text and each Version record whether their last Part is one, and the Post keeps the Format of a single X post. Parts already have an editor, a place in a Version and a way to publish as a reply to the Part before, so a First reply needs none of its own.

This amends ADR 0014 and ADR 0015. Their other decisions continue to apply.

## Rules

- Only a single X post has a First reply. A Thread's link goes in its last Part.
- The User can add, edit or delete the First reply on the Post page, as with any other Part.
- When Feedback turns a single X post into a Thread, the First reply's text moves into the Thread's last Part.
- A First reply the humanizer adds to a single X post that had none is dropped.
- Media stays on the post. A First reply carries none, and Media whose Part is gone after Feedback or a restore moves to the post, where in a Thread it moves to the last Part.
- Scheduling and Post now are refused while any Part of the Text contains the `[link]` placeholder, which the writing leaves where the User's real link goes, with a message naming it.

## Publishing (amends ADR 0014)

A single X post with a First reply publishes as two Parts: the post, then the First reply as a reply to it. ADR 0014's rules for a Thread apply to it. Each Part is published at most once. When X has accepted the post and the First reply is refused or its outcome is unknown, the Scheduled post becomes Failed, the post stays on X and is locked, and rescheduling publishes only the First reply.

## One Scheduled post (amends ADR 0015)

A Post still goes out once and has at most one Scheduled post. That Scheduled post is now a single X post, with its First reply when it has one, or a Thread, published at one time. The post and its First reply are not two Posts and never have two statuses.

## The Allowance

A First reply is an X post like any other Part. Once it is scheduled or posted now it counts as one X post of the Allowance, and as a Link post when its text contains a link by X's link rule, the same rules each Part of a Thread follows. Counting it any other way would leave an X post that X publishes and the Allowance doesn't see.

## Considered Options

- **A First reply as its own record beside the Text.** It would need its own editor, its own copy on every Version and Scheduled post, and its own publish step with its own failure handling. A Part has all of these.
- **A single X post with a First reply becomes a Thread.** The Plan's Length and the prompts for a single X post apply only to that Format, so the Post keeps it and gains a Part.
