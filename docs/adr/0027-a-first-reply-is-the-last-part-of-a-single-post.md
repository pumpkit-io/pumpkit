# A first reply is the last Part of a single post

Pumpkit's writing puts an external link in a first reply, a reply the User's account posts under its own post, so the post itself isn't penalised for carrying the link. A first reply is stored as the last Part of a single post's Text. The Text and each Version record whether their last Part is one, and the Post keeps the Format of a single post. Parts already have an editor, a place in a Version and a way to publish as a reply to the Part before, so a first reply needs none of its own.

This amends ADR 0014 and ADR 0015. Their other decisions continue to apply.

## Rules

- Only a single post has a first reply. A Thread's link goes in its last Part.
- The User can add, edit or delete the first reply on the Post page, as with any other Part.
- When Feedback turns a post into a Thread, the first reply's content moves into the Thread's last Part.
- A first reply the humanizer adds to a post that had none is dropped.
- Scheduling and Post now are refused while any Part of the Text contains the `[link]` placeholder, with a message naming it.

## Publishing (amends ADR 0014)

A single post with a first reply publishes as a chain of two Parts: the post, then the first reply as a reply to it. ADR 0014's rules for a Thread apply to it. Each Part is published at most once. When the post is live and the first reply is refused or its outcome is unknown, the Scheduled post becomes Failed, the live post is kept and locked, and rescheduling publishes only the first reply.

## One Scheduled post (amends ADR 0015)

A Post still goes out once and has at most one Scheduled post. That Scheduled post is now one X post, one Thread, or one X post with its first reply, published at one time. The post and its first reply are not two Posts and never have two statuses.

The Ticket that publishes first replies settles whether a first reply counts as an X post and a Link post of the Allowance.

## Considered Options

- **A first reply as its own record beside the Text.** It would need its own editor, its own copy on every Version and Scheduled post, and its own publish step with its own failure handling. A Part has all of these.
- **A post with a first reply becomes a Thread.** The Plan's Length and the post prompts apply only to a single post, so the Post keeps that Format and gains a Part.
