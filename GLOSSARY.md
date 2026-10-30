# Pumpkit

Open-source AI writing tool for X: turns a brief into a post written in the style of X authors you choose, then revises it with your feedback.

## Language

### Instances

**Instance**:
One running copy of Pumpkit, with its own Users and data. The Operator runs the hosted Instance at pumpkit.io; anyone may run their own from the open-source code.
_Avoid_: deployment, server, tenant, edition

**Self-hoster**:
A person who runs their own Instance. They are not the Operator, and the Operator's Terms and Privacy Policy do not cover their Instance.
_Avoid_: admin, host, operator (for anyone but the Operator)

**Sign-up allowlist**:
The email addresses and email domains that may sign in to an Instance. An Instance without one lets anyone sign in.
_Avoid_: whitelist, invite list, access list

### Accounts

**User**:
A person with a Pumpkit account, identified by their email address.
_Avoid_: account holder, customer (in auth contexts)

**Photo**:
The picture a User is shown with in Pumpkit. The User may upload one, take it from their Google account, their Gravatar or their X connection, or have none and be shown by their initials. Once a User has chosen or removed a Photo, Pumpkit never replaces it on its own. An X account and an Inspiration author also have a photo, the one X shows for them.
_Avoid_: avatar, profile picture, pfp

**Sign-in method**:
A way a User proves who they are to Pumpkit. The only Sign-in methods are Google and Magic link (see ADR 0002).
_Avoid_: auth provider, login method, first-party auth, third-party auth

**Magic link**:
A single-use, short-lived link emailed to a User that signs them in when opened.
_Avoid_: email login, passwordless link

**Google identity**:
The link between a User and the Google account they sign in with.
_Avoid_: third-party auth, OAuth identity

**Session**:
A User's signed-in presence in one browser, from sign-in until sign-out, expiry or revocation. It survives token refreshes.
_Avoid_: auth session, token family, login

**Suspended**:
A User who may not sign in or keep any Session until the suspension ends; a permanent suspension has no practical end.
_Avoid_: banned, inactive, deactivated

**API key**:
A secret a User creates so a program, such as Claude Code, can use Pumpkit on their behalf. It is never a Sign-in method and never opens a Session. A User may hold several, each with a name, and can revoke any of them at any time.
_Avoid_: token, access token, personal access token, credential

### Billing

**Plan**:
A recurring offer a User can subscribe to. Each Instance decides which Plans exist; nothing else is purchasable. An Instance may sell no Plans, and then every User may use all of Pumpkit without a Subscription.
_Avoid_: price, tier, product

**Subscription**:
A User's ongoing paid or trialling commitment to one Plan. A User has at most one Running Subscription; a User may hold several Ended ones from the past.
_Avoid_: membership, purchase

**Running**:
A Subscription that has started and not Ended: trialling, paid up, behind on payment, or paused. A Subscription whose first payment is still waiting on the User is not yet Running.
_Avoid_: live, active (for this broader sense)

**Ended**:
A Subscription that can never run again: it was cancelled, or its first payment never went through in time.
_Avoid_: inactive, expired (for Subscriptions)

**Subscribed**:
A User whose Subscription currently grants access to Pumpkit: it is in its Trial, paid up, or behind on payment while the billing provider still retries the charge.
_Avoid_: active, paying, premium

**Trial**:
The free, card-backed opening period of a User's first Subscription. Each User gets at most one.
_Avoid_: free tier, cardless trial

### Writing

**Inspiration author**:
An X account whose recent posts set the writing style of a User's posts, and never their content. Each User picks their own, up to three.
_Avoid_: creator, voice, style source

**Persona**:
A User's Inspiration authors taken together, up to three. It sets how the User's Posts sound, and never what they say. A User with no Inspiration authors has an empty Persona and cannot start a Post.
_Avoid_: voice, style, profile

**Brief**:
What a User writes to say what a Post is about and what they think about it. It is the Post's content, and the Inspiration authors are only its form.
_Avoid_: prompt, topic, input

**Post**:
One piece of writing made from one Brief: its Text, and every Version Pumpkit has written for it. Its Versions may differ in Format. A Post goes out at most once, so it has at most one Scheduled post, and takes its status from it: Scheduled while it waits or is being published, then Published or Failed. A Post with no Scheduled post is a Draft.
_Avoid_: tweet, run

**Draft**:
A Post that has at least one Version and no Scheduled post: it was never scheduled, or the User unscheduled it.
_Avoid_: unpublished post, not published

**Text**:
The one text a Post has at any time, the text meant for X. It is what the User reads and edits on the Post, what Feedback rewrites, and what a Scheduled post is copied from. It starts as the first Version and changes when the User edits it, sends Feedback, or restores a Version. A Thread's Text has one text per Part.
_Avoid_: working text, current version, content

**Version**:
A Text Pumpkit wrote for a Post. The first comes from the Brief, and each later one from one piece of Feedback on the Post's Text as it was then. Versions are numbered in the order Pumpkit wrote them and none is ever removed. Each Version has one Format, and a Thread's Version has one text per Part. Pumpkit writes a Sketch first and rewrites it into the Version's text.
_Avoid_: revision, iteration, round, snapshot, Final, final version

**History**:
Every Version of a Post in the order Pumpkit wrote them, each with the Brief or Feedback it came from. Restoring a Version makes it the Post's Text again. Editing the Text and undoing never change History.
_Avoid_: version history, log, timeline

**Starting text**:
The Post's Text a piece of Feedback was given on, kept with the Version it made when it differs from the Version before: the User edited the Text, or went back to an earlier Version, before sending.
_Avoid_: base text, input, source text

**Format**:
The shape of a Version's text: a single X post, or a Thread. The User picks it when starting a Post, a single X post unless they say otherwise, and may change it with any Feedback; Versions already written keep theirs. Editing the Text never changes its Format.
_Avoid_: type, mode, kind

**Thread**:
Text made of several ordered Parts, published on X with each Part replying to the one before. A Text, a Version or a Scheduled post may be a Thread.
_Avoid_: tweetstorm, chain, multi-post

**Part**:
One X post within a Thread, in its place in the order.
_Avoid_: tweet, segment, item

**Sketch**:
The text Pumpkit writes first in a Version, Hook included, before it is rewritten to sound like a person typed it. Users never see it.
_Avoid_: draft, first pass, raw output

**Hook**:
The opening of a Post's text: the line or lines meant to make a reader stop and read the rest. Pumpkit writes it as part of the Sketch, from its library of proven openings when one fits, and changes it in a later Version only when the Feedback asks. In a Thread, the Hook opens the first Part.
_Avoid_: headline, intro, opener, lede

**Feedback**:
What a User tells Pumpkit to change about a Post's Text as it is when they send it, their own edits included. It makes the next Version. Only a Draft or a Failed Post takes it: to revise a scheduled Post, the User unschedules it first, and a Published Post is finished.
_Avoid_: revision request, comment, instruction

### Publishing

**X connection**:
A User's permission for Pumpkit to publish on one X account they own. Each User has at most one, and an X account belongs to at most one User. It is never a Sign-in method.
_Avoid_: X login, X identity, linked account, X auth

**Community**:
An X Community: a group on X whose posts appear in the group rather than on each author's profile. A Scheduled post may go to one Community instead of the User's profile; it is still posted by the X account of the User's X connection, and the User chooses whether it is also shared with that account's followers.
_Avoid_: group, X group, space

**Destination**:
Where a Scheduled post goes: the profile of the X account of the User's X connection, or one Community.
_Avoid_: target, location, channel

**Scheduled post**:
A Post's Text a User has set to be published at a chosen time by the X account of their X connection, at its Destination. It is always copied from the Post's Text, and a Post has at most one. One Scheduled post is one X post, or one Thread published at one time; posting the same text in two places takes two Posts. It keeps its own copy of the text, which the User may edit, and stays a Scheduled post after it is Published or Failed. Unscheduling a waiting one deletes it and makes its Post a Draft again.
_Avoid_: queued tweet, publication, scheduled tweet

**Published**:
A Scheduled post that X has accepted and shows on the User's X account, or in its Community; for a Thread, every Part has been accepted. It can no longer change.
_Avoid_: posted, sent, live

**Failed**:
A Scheduled post Pumpkit gave up publishing, with a reason the User can read. The User may edit and reschedule it, also with its Post's Text as edited or rewritten since. A Thread may fail after some of its Parts are live; those Parts can no longer change, and rescheduling publishes only the rest.
_Avoid_: errored, rejected, dead

### Legal

**Operator**:
The company that runs the hosted Instance at pumpkit.io and is the other party to the Terms: INCEPTIONAL S.R.L. Self-hosters' Instances are not covered by the Operator's Terms or Privacy Policy.
_Avoid_: we (in docs), owner, provider, Pumpkit (for the company)

**Terms**:
The contract between the Operator and a User for using the hosted Pumpkit, in English and Italian with both versions equally valid. A User accepts them before every checkout, so each Subscription has its own acceptance (see ADR 0010).
_Avoid_: ToS, terms and conditions, EULA, user agreement

**Privacy Policy**:
The Operator's notice of which personal data the hosted Pumpkit processes, why, with whom, for how long, and how people exercise their rights over it.
_Avoid_: privacy notice, data policy, cookie policy (it covers cookies too)

**Analytics consent**:
A visitor's choice to allow or refuse product analytics and session recording in their browser. Until they allow it, Pumpkit sends nothing to the analytics provider.
_Avoid_: cookie consent, tracking consent, GDPR consent
