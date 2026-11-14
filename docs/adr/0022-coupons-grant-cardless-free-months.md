# Coupons grant cardless free months, including to existing subscribers

ADR 0023 extends the repeat-redemption restriction below to both the X account and verified email, including across account deletion. Receiving Coupon benefits also removes that X account’s Trial eligibility across deletion and recreation.

ADR 0028 narrows the paid-signup mechanics below: a paid Subscription arranged after Free access starts from one subscription-mode Checkout carrying the first payment date, not from a saved card and a Subscription created outside Checkout.

Coupons give Users free months of Pro without requiring a payment card or creating an obligation to pay afterward. Existing subscribers, including annual subscribers, may redeem them too: their benefit must defer or reduce payment rather than overlap access they already paid for. A User without a paid Subscription meets the Paywall when free access ends unless they choose to subscribe.

This narrows ADR 0003’s subscription-only premise, ADR 0010’s checkout-only acceptance premise, ADR 0017’s Top-up purchase eligibility and ADR 0018’s Subscription-only access premise. A Coupon is not the existing card-backed Trial.

A Coupon may be reserved for a verified email address before its recipient signs up, or available to anyone. Each Coupon has a configurable total redemption limit, defaulting to one, at most one redemption per X account and per verified email address, including after account deletion, and an optional claim deadline.

## Time and renewal

Free months are calendar months, using Pumpkit's existing short-month rules. Each free month provides the full Pro Allowance, with monthly resets. Redemption during a paid period does not reset usage immediately.

Free months append to existing paid or free time. Different Coupons stack; a claim deadline limits redemption, not when queued free time may run. Existing subscribers have their next renewal postponed by the free months, including annual subscribers. For example, three free months move a December 1 annual renewal to March 1. The Subscription then continues under the User's existing renewal choice. A cancellation stays cancelled, with free access after paid time ends. A Coupon creates no new payment commitment.

Receiving free months removes eligibility to start a new introductory Trial. Users with neither Coupon benefits nor Subscription history retain their normal Trial eligibility.

A User already in a Trial finishes it under its existing Allowance before queued free months begin. Their first payment is postponed. Coupon-only Users may arrange a paid Subscription before free access ends, explicitly accepting the Plan and future charge date. Payment starts after remaining free time; arranging it early neither charges immediately nor discards that time.

Redemption is refused without consuming the Coupon while a Subscription has an unpaid invoice or a payment still processing. The User must resolve that billing state first. Coupons do not forgive outstanding debt.

## Access and redemption

Coupon-only Users may buy Top-ups and spend previously purchased ones, under their existing prices, expiry and usage rules. This broadens ADR 0017's purchase eligibility beyond paid-up paid Subscriptions.

The Paywall offers an expandable "Have a coupon?" form before paid checkout. Settings offers "Redeem coupon" in the Plan card. Both check the code and preview the exact free period and payment consequences before confirmation. After redemption, new Users continue into Onboarding. These forms reuse the app's existing typography, colours and components; there is no separate Coupon dashboard or new visual direction.

Redemption requires acceptance of the current Terms, recorded for that redemption. Cardless redemption describes free access and its end date. Paid subscription commitments belong in the later subscription flow. The bilingual copy, two-box cardless acceptance evidence and separate paid acceptance contract are recorded in [the Coupon contract](../coupons.md#acceptance-contract).

## Issuance and lifecycle

A command-line tool creates, inspects, lists and disables Coupons; no administration UI is needed. Creation takes the number of months, an optional recipient email, a total redemption limit and an optional claim deadline. Randomly generated codes work only on the issuing Instance. Issuance requires privileged access to that Instance, so publishing the tool's source grants no issuance authority.

Use cryptographically random, high-entropy opaque codes backed by Instance records, storing their digests rather than recoverable plaintext. Creation delivers the code to the person running the command; application logs, analytics and URLs must not receive it. Issuance has no public app endpoint. Redemption requires a signed-in User, server-side eligibility checks and rate limiting. A preview reserves neither a redemption slot nor its displayed dates; confirmation revalidates both, and a changed offer must be shown again before acceptance.

Disabling a Coupon stops future claims and preserves benefits already redeemed. Removing an individual's granted benefits is a separate support action outside this implementation, because shortening free time could bring a payment forward unexpectedly.

Deleting and recreating an account, changing its email, or using a distinct X account with the same email does not permit a second claim of the same Coupon by either identity (ADR 0023). Keep a minimal, protected claim record while that Coupon remains redeemable, including across account deletion. The [retention and key-custody contract](../coupons.md#retention-and-purge) sets precise purge periods, account-deletion handling and key rotation. The English and Italian Privacy Policy describes fingerprints as pseudonymous personal data, including indefinite claim prevention for redeemable no-deadline codes. This does not prevent one person using distinct X accounts with distinct verified emails; recipient assignment and total redemption limits still apply.

Coupons are available only on Instances that sell Plans. Instances without billing already grant unrestricted access. Self-hosters with billing configured use the same public tooling to issue their own Coupons, consistent with ADR 0011.

## Local benefits and provider billing

Coupons, their redemptions and Free access periods belong in Pumpkit's billing area. Stripe remains authoritative for actual Subscriptions, as ADR 0004 requires. A cardless recipient gets no fabricated Subscription. Access and Allowances must account for local Free access, independently of Stripe's status or trial dates. The glossary's Subscribed term includes a User currently receiving Free access; it does not imply that User has a Subscription.

Use Stripe's existing trial-period mechanism to defer an existing or explicitly arranged Subscription's renewal, subject to test-mode verification with the integration's API version and billing modes. Preserve paid and introductory Trial Allowance boundaries locally: a provider deferral must not turn already-paid time or Coupon months into Pumpkit's reduced Trial Allowance. The existing action that ends an introductory Trial early must not charge away Coupon benefits.

The resulting payment date must fit Stripe's supported 730-day horizon, including remaining paid time. Different Coupons still stack within that limit. Refuse an unsupported redemption without consuming the Coupon. Apply the same horizon to cardless Free access so arranging a paid Subscription later remains possible.

Cancelling future renewal preserves all remaining paid and free time. Changes between monthly and annual billing take effect after Free access ends, without an immediate charge. Refuse redemption without consuming the Coupon when an incompatible plan change is already pending. Portal configuration and app actions must preserve these rules.

Keep the benefit representation specific and extensible: Free access is the first supported benefit. Future duration units or extra Allowance benefits can be added when their rules are decided; this work does not implement them or a general promotion rules engine.

## UI design plan

Keep the existing visual identity: Inter Variable for form and status text, the app's established type scale, Pumpkin #D96B45, Charcoal #20201E, Ivory #F7F5EF, Olive #66734E and white #FFFFFF, through existing semantic light and dark theme tokens. These palette references do not replace the existing accessible control colours. Use the current card, input, button, notice and error components, with left-aligned content and the existing Settings column width. A narrow viewport stacks the code field and action vertically. The only emphasis is the benefit and its actual dates; a Coupon does not need promotional artwork, confetti or a separate page.

The shared form follows this sequence:

```text
Have a coupon? / Redeem coupon
  Coupon code [                 ]  [Check code]
  Benefit, start date and end date
  Next payment date and plan, or no automatic payment
  Terms acceptance
  [Redeem coupon]
```

Before entry, show an empty code field and disable checking an empty value. While checking or redeeming, show progress and prevent duplicate submissions. An unavailable, expired, disabled, exhausted or ineligible code gets an inline explanation without exposing another recipient's identity; a transport error offers retry without clearing the field. If a provider result is uncertain, show that redemption is being confirmed rather than claiming failure or inviting a second billing operation. Success shows the granted dates and the next step, with no automatic paid signup. A changed preview returns to review.

Settings shows current or queued Free access in the Plan card, including its dates, the next payment date if one is agreed, and the next Allowance reset through the Usage card. Loading and fetch errors use existing progress and retry states. At the known end of access, the existing Paywall applies; scheduling and publishing checks must use the same access horizon. The specification must include keyboard interaction, focus after state changes, announced results, responsive layout and both themes.

This plan extends the existing billing UI rather than setting a new design direction. Its review against the brief keeps redemption before onboarding, visible payment consequences before confirmation and no additional dashboard.

## Final validation before activation

The maintainer’s November 8, 2026 execution policy in spec #392 replaces the earlier pre-implementation validation gate. Implement and review #395–#405 with normal checks, fake gateways and adapter contracts, then run final #394 after all implementation PRs merge. One shared Instance setting, `COUPONS_ENABLED`, stays false by default: no issuance, redemption, coupon-specific paid actions or Coupon affordances until enabled. Instances that sell no Plans retain unrestricted access. Real Stripe credentials and Dashboard access are required only for final validation.

The `pro-coupons-t394` branch supplied the initial API/portal evidence and opt-in harness. The [November 9 merged-application validation](../stripe-coupon-verification.md) now records test-mode hosted Checkout through the first monthly and annual payment, renewal/cancellation, recovery, calendar boundaries and corrected classic interval changes. Authenticated reminder/notice inspection found generic reminder emails off in both accounts. An already-open portal price confirmation succeeded after feature restriction alone (#430). The [November 10 transition verification](../stripe-portal-transition.md) supplies conditional, provider-backed safeguards; each instance must satisfy them and final #394 before activation. The implementation and operator handoff is [documented separately](../coupons.md), including activation, acceptance and retention.

Before activation, verify the installed Stripe integration in test mode for monthly and annual renewal deferral, an existing Trial, short months and leap years, repeated redemptions, cancellation before and during Free access, early arrangement of paid renewal, and portal actions. Confirm no immediate charge, lost paid time, lost free time or unintended Allowance reset. A provider limitation that breaks these promises reopens the billing approach rather than silently changing the product rules.

Stripe changes and a local database transaction are not atomic. Implementation must retain enough durable operation state to reconcile an uncertain provider result and retry safely. Never report redemption success until the necessary billing change is confirmed, and never grant duplicate benefits or oversubscribe a Coupon's redemption limit under concurrent claims.

## Considered billing approaches

- Stripe discounts alone. They do not represent cardless local access or the intended future benefit types.
- Stripe subscription schedules. They can represent paid, free and paid phases, but prevent updates and cancellation in the customer portal while an update is scheduled. That would require additional cancellation controls in Pumpkit. The bounded deferral approach keeps this implementation smaller.
- An unbounded queue with a single Stripe trial period. Stripe limits trial periods to 730 days, so arbitrary stacking cannot be promised through this mechanism.

Sources: [renewal deferral](https://docs.stripe.com/billing/subscriptions/billing-cycle#change-the-billing-period-using-a-trial-period), [trial periods and their limit](https://docs.stripe.com/billing/subscriptions/trials/free-trials), [customer portal restrictions](https://docs.stripe.com/customer-management#limitations).

## Considered options

- Requiring a card and automatically charging after the free period. Recipients should be able to use their free months without taking on a future payment.
- Granting access alongside an existing paid Subscription without changing payment. That gives existing subscribers no benefit, especially when they already paid for a year.

## Deferred interval implementation

Monthly/annual changes during current or queued Free access use a durable in-app subscription-item price update on the installed API, with no proration and unchanged anchor. The price changes in Stripe immediately; payment begins at the preserved free end, and original paid/Trial coverage and accepted Allowance caps remain local authority. No schedule or API upgrade is introduced. Pending changes serialize with redemption and paid signup; bounded same-key recovery preserves cancellation and never guesses the outcome of a late write. The detailed checkpoint, retention and API contract is in [the complete flow](../coupons.md#deferred-billing-frequency-changes).

An explicit validated management-only portal replaces unrestricted sessions while Coupons are enabled, including for ordinary subscribers who might redeem later. Subscription updates, cancellation and login are disabled there; Settings supplies cancellation and frequency changes. This is narrower than the historical `continue_trial` price-change portal candidate. Existing sessions and external login links still require provider-backed activation safeguards; naming a new configuration does not establish revocation. Final #394 must validate the merged integration and those outstanding-session paths before enabling Coupons.

The [November 10 portal transition verification](../stripe-portal-transition.md) distinguishes permanent deactivation of non-default legacy configurations from a clean start whose historical customers are detached and subscriptions already ended. Its opt-in browser matrix checks stale update/cancellation submissions in both billing modes, replacement-customer isolation and disabled old logins. Feature restriction alone and an assumed one-hour drain remain insufficient. The clean-start procedure never authorizes cancelling subscribers or discarding benefits; instances with unresolved historical commitments remain gated. Final #394 still requires the complete merged application and instance prerequisites before activation.
