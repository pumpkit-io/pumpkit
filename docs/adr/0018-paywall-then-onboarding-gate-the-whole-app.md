# The Paywall and Onboarding gate the whole app, backend included

ADR 0023 removes the separate X connection step from Onboarding below: X is authorized at sign-in, then the Paywall and Persona setup retain their order. The usual access gates remain; ADR 0023 also permits authenticated same-account X recovery without a paid Subscription.

ADR 0024 amends the Persona step below: it asks for a Positioning in place of an Inspiration author, and is done when one exists.

## Historical decision

On an Instance that sells Plans, a signed-in User who is not Subscribed sees only the Paywall, and every area route on the backend refuses them, reads included. Only auth, the User's own account, billing, `/instance` and the Onboarding state (`GET /onboarding`) stay open, so they can still subscribe, sign out or delete their account, and the web app knows to show them the Paywall. Until now only writes needed a subscription and each page showed its own Subscribe prompt. That left the app open to look around in without paying, which the Operator doesn't want. The Paywall is checked on every visit, so a User whose Subscription Ends meets it again.

Onboarding (connect X, then choose a Persona) comes after the Paywall and happens once. Each step counts as done when what it asks for exists: an X connection, at least one Inspiration author. Refreshing, signing out or switching browsers therefore resumes at the right step. The one stored fact is when the User finished Onboarding. After that, disconnecting X or emptying the Persona never sends them back. A step the Instance can't offer is skipped: the X step on an Instance without X configured, and the Paywall on one that sells no Plans.

ADR 0022 narrows the Subscription-only access premise: current local Free access also makes a User Subscribed, including without a Stripe Subscription. The Paywall and Onboarding order and backend/Connected app gates stay unchanged; they use effective access and its expiry. See [the Coupon contract](../coupons.md).

## Considered Options

- **A gate in the frontend only.** It is cheaper, but the API and the MCP server would still serve an unsubscribed User's data, so the wall would exist only in the UI.
- **A stored current step per User.** It can disagree with the data, for example when X is connected from another tab, and would need its own transitions kept in sync with every area.
- **Onboarding worked out from data alone, with nothing stored.** A User who disconnects X later would be thrown back into Onboarding.
