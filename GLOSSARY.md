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
The text Pumpkit writes first in a Version, Hook included, before it is rewritten to sound like a person typed it.
_Avoid_: first pass, raw output

**Hook**:
The opening of a Post's text: the line or lines meant to make a reader stop and read the rest. Pumpkit writes a new one when a Version needs it and the User has not dictated the opening, and never changes the text after it.
_Avoid_: headline, intro, opener, lede

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

**Community**:
An X Community: a group on X whose posts appear in the group rather than on each author's profile. A Scheduled post may go to one Community instead of the User's profile; it is still posted by the X account of the User's X connection, and the User chooses whether it is also shared with that account's followers.
_Avoid_: group, X group, space

**Destination**:
Where a Scheduled post goes: the profile of the X account of the User's X connection, or one Community.
_Avoid_: target, location, channel

**Scheduled post**:
A text a User has set to be published at a chosen time by the X account of their X connection, at its Destination. It is either typed by the User or copied from a Version's Final. One Scheduled post is one X post; posting the same text in two places takes two Scheduled posts. It keeps its own copy of the text and stays a Scheduled post after it is Published or Failed.
_Avoid_: queued tweet, publication, scheduled tweet

**Published**:
A Scheduled post that X has accepted and shows on the User's X account, or in its Community. It can no longer change.
_Avoid_: posted, sent, live

**Failed**:
A Scheduled post Pumpkit gave up publishing, with a reason the User can read. The User may edit and reschedule it.
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
