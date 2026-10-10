# Pumpkit

Open-source AI writing tool for X: turns a brief into a post written in the style of X authors you choose, then revises it with your feedback.

## Language

### Accounts

**User**:
A person with a Pumpkit account, identified by their email address.
_Avoid_: account holder, customer (in auth contexts)

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

### Billing

**Plan**:
A recurring offer a User can subscribe to. Pumpkit decides which Plans exist; nothing else is purchasable.
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

**Brief**:
What a User writes to say what a Post is about and what they think about it. It is the Post's content, and the Inspiration authors are only its form.
_Avoid_: prompt, topic, input

**Post**:
One piece of writing made from one Brief, with every Version it has been through.
_Avoid_: tweet, run, thread

**Version**:
One round of a Post's text. The first comes from the Brief, and each later one comes from a piece of Feedback on the one before.
_Avoid_: revision, iteration, round

**Draft**:
The text Pumpkit writes first in a Version, before it is rewritten to sound like a person typed it.
_Avoid_: first pass, raw output

**Final**:
The rewritten text of a Version, the one meant to be pasted into X.
_Avoid_: humanized post, output, refined post

**Feedback**:
What a User tells Pumpkit to change about the latest Version of a Post.
_Avoid_: revision request, comment, instruction

### Publishing

**X connection**:
A User's permission for Pumpkit to publish on one X account they own. Each User has at most one, and an X account belongs to at most one User. It is never a Sign-in method.
_Avoid_: X login, X identity, linked account, X auth

**Scheduled post**:
A text a User has set to be published on the X account of their X connection at a chosen time, either typed by the User or copied from a Version's Final. It keeps its own copy of the text and stays a Scheduled post after it is Published or Failed.
_Avoid_: queued tweet, publication, scheduled tweet

**Published**:
A Scheduled post that X has accepted and shows on the User's X account. It can no longer change.
_Avoid_: posted, sent, live

**Failed**:
A Scheduled post Pumpkit gave up publishing, with a reason the User can read. The User may edit and reschedule it.
_Avoid_: errored, rejected, dead
