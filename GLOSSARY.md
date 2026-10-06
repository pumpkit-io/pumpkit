# Pumpkit

Open-source social listening and AI reply tool for X: finds conversations worth joining, drafts replies, and sends them to you on Telegram for approval before posting.

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

**Connected X account**:
An X account a User has authorised Pumpkit to act on, for example to post approved replies. It is never a Sign-in method.
_Avoid_: X login, X identity

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
