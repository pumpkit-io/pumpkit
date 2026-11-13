# Pumpkit

Open-source AI writing tool for X: turns a brief into a post written in the style of X authors you choose, then revises it with your feedback.

## Language

The _Avoid_ lists don't bind the Pro offer's marketing copy or its info popovers, wherever they appear (the Usage card included): there, "prompt" and "X creators" may stand for a Generation and Inspiration authors.

### Instances

**Instance**:
One running copy of Pumpkit, with its own Users and data. The Operator runs the hosted Instance at pumpkit.io; anyone may run their own from the open-source code.
_Avoid_: deployment, server, tenant, edition

**Self-hoster**:
A person who runs their own Instance. They are not the Operator, and the Operator's Terms and Privacy Policy do not cover their Instance.
_Avoid_: admin, host, operator (for anyone but the Operator)

**Release**:
A numbered copy of Pumpkit, `X.Y.Z`, that Self-hosters and the Operator install on their Instance, with its CHANGELOG section as its notes. Its number is not a Version, which belongs to a Post.
_Avoid_: version (for a Release), build, deploy

**Upgrade notes**:
The manual steps a Release's CHANGELOG entries ask of an Instance that upgrades to it, written for any Instance, such as a new required setting or a step for a Self-hoster's own proxy. An entry with nothing to do by hand has none.
_Avoid_: migration notes, breaking changes, manual steps (as a name)

**Sign-up allowlist**:
The email addresses and email domains that may sign in to an Instance. An Instance without one lets anyone sign in.
_Avoid_: whitelist, invite list, access list

### Accounts

**User**:
A person with a Pumpkit account, identified by the X account they sign in with.
_Avoid_: account holder, customer (in auth contexts)

**Photo**:
The picture a User is shown with in Pumpkit, taken from their X account. A User with no X photo is shown by their initials; an Inspiration author also has the photo X shows for them.
_Avoid_: avatar, profile picture, pfp

**Sign-in method**:
A way a User proves who they are to Pumpkit. X is the only Sign-in method (see ADR 0023).
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

**Onboarding**:
The steps a User goes through once, after the Paywall and before the rest of Pumpkit opens: setting up their Persona by saving a Positioning. Each step counts as done when what it asks for exists. Once a User finishes Onboarding they never see it again, even if they later empty their Persona.
_Avoid_: setup wizard, first run, welcome flow

**Connected app**:
A program, such as Claude, ChatGPT or Claude Code, that a User allowed in their browser to use Pumpkit on their behalf. It is never a Sign-in method and never opens a Session. A User can disconnect any of them at any time, in Settings.
_Avoid_: OAuth client, integration, connector, grant, authorized app

### Billing

**Coupon**:
A code a User redeems for a benefit, currently free months of the configured Plan offer (Pro on pumpkit.io). It may be reserved for one email address, even before sign-up, or open to anyone, with a total redemption limit, at most one redemption per X account and per verified email address, including across account deletion, and an optional claim deadline.
_Avoid_: voucher, promo code, discount code

**Free access**:
The months of the configured Plan offer a redeemed Coupon gives a User, each with the full monthly Allowance. They follow any remaining paid time or Trial, stack with other free months, and create no obligation to subscribe or pay.
_Avoid_: Trial (for Coupon benefits), free Subscription

**Plan**:
A recurring offer a User can subscribe to. Each Instance decides which Plans exist; besides them, only Top-ups are purchasable. An Instance may sell no Plans, and then every User may use all of Pumpkit without a Subscription. It is not an Idea's Plan, which belongs to the writing.
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
A User who currently has access to Pumpkit through Free access or a Subscription in its Trial, paid up, or behind on payment while the billing provider still retries the charge.
_Avoid_: active, paying, premium

**Trial**:
The free, card-backed opening period of a User's first Subscription. Each X account gets at most one per Instance, including after account deletion and recreation, and receiving Free access removes eligibility to start a new one.
_Avoid_: free tier, cardless trial

**Paywall**:
The page a signed-in User who is not Subscribed sees in place of the rest of Pumpkit, where they redeem a Coupon, start their Trial or subscribe to a Plan. It is checked on every visit, not only the first. An Instance that sells no Plans has no Paywall.
_Avoid_: subscription gate, upgrade screen, hard wall

**Allowance**:
How much a Subscribed User may write and publish in one Allowance period: a number of Generations, and a number of X posts, a few of which may be Link posts. Each Part of a Thread is one X post. An X post counts once it is scheduled or posted now, and stops counting if it is unscheduled or fails without X accepting it. What is left at the end of a period does not carry over. Monthly and annual Plans and each month of Free access give the same full monthly Allowance. A Trial has its own, smaller Allowance. An Instance that sells no Plans has no Allowances.
_Avoid_: quota, usage limit, credits, cap (in text users read; setting names and code may say cap)

**Link post**:
An X post whose text contains a link, by the rule X uses to spot links when it counts a post's length. It counts against both the X posts and the Link posts of an Allowance or a Top-up.
_Avoid_: URL post, linked tweet, link X post

**Generation**:
One Version Pumpkit writes for a User, as an Allowance or a Top-up counts it: each Post written from a Brief is one, and so is each Feedback. Planning a Brief, drafting a Positioning and a writing attempt that fails are not Generations.
_Avoid_: prompt, post prompt, credit, request

**Allowance period**:
The stretch of time one Allowance covers. Paid Subscriptions and Free access have monthly periods, also on annual Plans; the first paid or free period sets its recurring monthly day. A Trial is one Allowance period on its own, and paying before it ends starts the first monthly one at once.
_Avoid_: billing cycle, billing period, month (alone)

**Top-up**:
A one-off purchase of extra Generations and X posts for a User who has used up their Allowance. It is spent only after the Allowance, lasts 12 months from purchase, and only a Subscribed User can spend it. A User with Free access or a paid-up paid Subscription may buy one. It is never part of a Plan.
_Avoid_: credits, credit pack, add-on, extra usage

### Writing

**Positioning**:
A User's own account of who they are on X, what they post about, who they write for, what they post for and what they can point readers to, as one free text. Pumpkit drafts it from their X profile and recent posts, and the User edits it.
_Avoid_: bio, profile, niche, brand

**Persona**:
What Pumpkit writes a User's Posts around: their Positioning. It is also the name of the page where they edit it. A User with no Positioning has an empty Persona and cannot plan a Brief.
_Avoid_: voice, style, profile

**Inspiration author**:
An X account whose recent posts set the writing style of a User's posts, and never their content. Inactive since ADR 0024: Positioning replaced Inspiration authors as the Persona, and no User can pick one.
_Avoid_: creator, voice, style source

**Author directory**:
The X accounts an Instance knows, each with its handle, name and photo, shared by all its Users, from which a User picked Inspiration authors. Inactive since ADR 0024: no User can pick from it or add to it.
_Avoid_: catalog, pool, library, collection

**Brief**:
What a User writes to say what they want to post about and what they think about it. Pumpkit plans it into one or more Ideas, and it is the content of every Post written from it. It keeps the Positioning it was planned with.
_Avoid_: prompt, topic, input

**Idea**:
One Post Pumpkit proposes from a Brief, with its Plan: a single Post covering the whole Brief, or one of up to five separate ones in posting order. Every Idea is kept, written or not, and has at most one Post.
_Avoid_: topic, suggestion, angle

**Plan** (of an Idea):
What Pumpkit decides about an Idea before writing it: its core idea, takeaway, funnel stage, desired action, Format, Length and structure. Feedback may override any of it. It is not the Plan a User subscribes to.
_Avoid_: outline, strategy, blueprint

**Length**:
How long a Plan makes a single X post: short, medium or long, within the character limit of the User's X account. A Thread has none.
_Avoid_: size, word count

**Post**:
One piece of writing made from one Idea of a Brief: its Text, and every Version Pumpkit has written for it. A Brief may have several Posts. Its Versions may differ in Format. A Post goes out at most once, so it has at most one Scheduled post, and takes its status from it: Scheduled while it waits or is being published, then Published or Failed. A Post with no Scheduled post is a Draft, once its first Version is written.
_Avoid_: tweet, run

**Draft**:
A Post that has at least one Version and no Scheduled post: it was never scheduled, or the User unscheduled it.
_Avoid_: unpublished post, not published

**Text**:
The one text a Post has at any time, the text meant for X. It is what the User reads and edits on the Post, what Feedback rewrites, and what a Scheduled post is copied from. It starts as the first Version and changes when the User edits it, sends Feedback, or restores a Version. A Thread's Text has one text per Part. The Text also holds the Media the User attached; Versions never do.
_Avoid_: working text, current version, content

**Version**:
A Text Pumpkit wrote for a Post. The first comes from the Post's Idea and its Brief, and each later one from one piece of Feedback on the Post's Text as it was then. Versions are numbered in the order Pumpkit wrote them and none is ever removed. Each Version has one Format, and a Thread's Version has one text per Part. Pumpkit writes each one in the background: a Sketch first, then the Version's text rewritten from it.
_Avoid_: revision, iteration, round, snapshot, Final, final version

**History**:
Every Version of a Post in the order Pumpkit wrote them, each with the Brief or Feedback it came from. Restoring a Version makes it the Post's Text again. Editing the Text and undoing never change History. The button that opens it is labelled "Versions history".
_Avoid_: log, timeline

**Starting text**:
The Post's Text a piece of Feedback was given on, kept with the Version it made when it differs from the Version before: the User edited the Text, or went back to an earlier Version, before sending.
_Avoid_: base text, input, source text

**Format**:
The shape of a Version's text: a single X post, or a Thread. The Plan sets it for the first Version, following the Brief when it asks for one, and the User may change it with any Feedback; Versions already written keep theirs. Editing the Text never changes its Format.
_Avoid_: type, mode, kind

**Thread**:
Text made of several ordered Parts, published on X with each Part replying to the one before. A Text, a Version or a Scheduled post may be a Thread.
_Avoid_: tweetstorm, chain, multi-post

**Part**:
One X post within a Thread, in its place in the order. A single X post with a First reply has two Parts: the post and the reply.
_Avoid_: tweet, segment, item

**First reply**:
A reply to a single X post, published with it by the same X account, that carries what the post itself should not, such as an external link. It is the last Part of the Post's Text, and the Format stays a single X post. A Thread has none: its link goes in its last Part.
_Avoid_: self-reply, link reply, comment

**Media**:
The images, animated GIF or video a User attaches to a Post's Text, on its single X post or on one Part of a Thread, to be published with that X post on X. It is the User's own content, like a hand edit: Pumpkit's writing never sees it, Feedback and restoring a Version keep it on its Part, or move it to the last Part when that Part is gone, and only the User, or the AI app they ask, writes an image's alt text: Pumpkit's writing never does. Alt text belongs to the Media, so a Scheduled post's copy and the Text show the same alt text. One X post carries up to four images, or one GIF, or one video.
_Avoid_: attachment, file, asset, upload

**Upload link**:
A one-time link an AI app asks for to send a Media file from the User's computer to one Part of a Post, with no other credentials. It expires 15 minutes after it is made.
_Avoid_: upload URL, presigned URL, drop link

**Sketch**:
The text a Version is rewritten from, Hook included. For a Post's first Version, Pumpkit writes several attempts at once and merges them into the Sketch; it is then rewritten to sound like a person typed it. Users never see it.
_Avoid_: draft, first pass, raw output

**Hook**:
The opening of a Post's text: the line or lines meant to make a reader stop and read the rest. Pumpkit writes it as part of the Sketch, trying a different kind of opening in each attempt before the merge settles on one, and changes it in a later Version only when the Feedback asks. In a Thread, the Hook opens the first Part.
_Avoid_: headline, intro, opener, lede

**Feedback**:
What a User tells Pumpkit to change about a Post's Text as it is when they send it, their own edits included. It makes the next Version. Only a Draft or a Failed Post takes it: to revise a scheduled Post, the User unschedules it first, and a Published Post is finished.
_Avoid_: revision request, comment, instruction

### Publishing

**X connection**:
A User's permission for Pumpkit to publish on the X account they sign in with. Each User has at most one, and an X account belongs to at most one User.
_Avoid_: linked account, X auth

**Community**:
An X Community: a group on X whose posts appear in the group rather than on each author's profile. A Scheduled post may go to one Community instead of the User's profile; it is still posted by the X account of the User's X connection, and the User chooses whether it is also shared with that account's followers.
_Avoid_: group, X group, space

**Destination**:
Where a Scheduled post goes: the profile of the X account of the User's X connection, or one Community.
_Avoid_: target, location, channel

**Scheduled post**:
A Post's Text a User has set to be published at a chosen time by the X account of their X connection, at its Destination. It is always copied from the Post's Text, Media included, and a Post has at most one. One Scheduled post is one X post, one X post with its First reply, or one Thread, published at one time; posting the same text in two places takes two Posts. It keeps its own copy of the text, which the User may edit, and stays a Scheduled post after it is Published or Failed. Unscheduling a waiting one deletes it and makes its Post a Draft again.
_Avoid_: queued tweet, publication, scheduled tweet

**Posting**:
A Scheduled post being published, or whose time has come while it waits for its turn, until it is Published or Failed. Its Post stays Scheduled meanwhile: posting is not a status of its own.
_Avoid_: publishing, sending, in progress

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
The contract between the Operator and a User for using the hosted Pumpkit, in English and Italian with both versions equally valid. A User accepts them before every checkout and Coupon redemption, so each Subscription and redemption has its own acceptance (see ADR 0010 and ADR 0022).
_Avoid_: ToS, terms and conditions, EULA, user agreement

**Privacy Policy**:
The Operator's notice of which personal data the hosted Pumpkit processes, why, with whom, for how long, and how people exercise their rights over it.
_Avoid_: privacy notice, data policy, cookie policy (it covers cookies too)

**Analytics consent**:
A visitor's choice to allow or refuse product analytics and session recording in their browser. Until they allow it, Pumpkit sends nothing to the analytics provider.
_Avoid_: cookie consent, tracking consent, GDPR consent
