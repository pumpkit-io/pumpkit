# Coupon validation against Stripe test mode

## Status

The November 9, 2026 run validated merged main `ca29955e214fbf375673ecbcc3683f5eefbe8f1e` and the corrective changes for [#429](https://github.com/pumpkit-io/pumpkit/issues/429). All provider objects used test keys, synthetic customers and isolated products, prices, portal configurations and test clocks. No live payment was made. Stripe reported `livemode=false` before setup and on the created billing objects.

**The activation gate in #394 is still open.** Hosted Checkout and first paid renewals are now verified. Authenticated Dashboard settings and generic notice previews are recorded below. An outstanding portal confirmation still accepted a price change after configuration restriction ([#430](https://github.com/pumpkit-io/pumpkit/issues/430)); its safe transition remains unverified. Keep `COUPONS_ENABLED=false` outside isolated tests. Test-mode events do not establish notice wording or actual email delivery.

## Integration and method

- Installed integration: stripe-python `15.6.1`, API `2026-08-26.dahlia`; classic and flexible billing modes.
- The isolated worktree ran the merged application with its real Stripe gateway, PostgreSQL and visible Chrome. Synthetic account/onboarding fixtures avoided external Google/X actions. The app's existing clock dependency followed each Stripe test clock.
- A private, disposable gateway wrapper lost one acknowledgement after a successful real test-mode deferral, and another after a successful interval change. The browser then recovered the committed operation. No production test hook is added.
- Stripe CLI forwarded real signed test-mode subscription and Checkout events to the isolated app. Webhooks continued to read current provider truth. Setup transitions before the listener and backend shared a signing secret are not application-success evidence.
- Hosted Checkout used Stripe's published Visa test card, a synthetic US billing address, the real setup-mode Checkout created by Pumpkit, and its three-box paid acceptance. Setup completion and resulting subscription/invoice facts were retrieved before clocks advanced. The resulting subscriptions used the gateway's automatic-tax setting; these US fixtures did not exercise every tax jurisdiction or authentication challenge.
- Credentials, session URLs, customer identifiers, codes and session tokens stay in private gitignored artifacts. Screenshots contain only synthetic test data; they are not a source of notice-delivery claims.

## Results

| Case | Observed result |
| --- | --- |
| Monthly classic subscriber, repeated coupons | Two grants stacked after paid coverage, original usage/reset remained, no additional nonzero invoice on deferral, and a full paid month began at the final free end. |
| Monthly flexible to annual billing | The app changed the future price, preserved free/paid time and usage, added no immediate nonzero invoice, and resumed with a full paid year. |
| Annual classic to monthly billing | Initially failed with Stripe HTTP 400 for explicit `billing_cycle_anchor=unchanged`. The correction below passed the browser flow, lost-acknowledgement recovery and first full paid month. |
| Annual flexible cancellation during deferral | Cancellation retained the full free end; advancing through it ended the subscription without another payment. |
| Existing introductory trial, classic | The original reduced allowance, usage, reset and trial end remained; the full free month followed, then a full paid month. |
| Existing introductory trial, flexible, cancellation before claim | The claim retained cancellation and queued free access; the provider ended without a new charge. |
| January 31, 2028 monthly paid coverage | Free access began February 29, ended March 31, and the first paid month ended April 30. |
| Cardless monthly paid arrangement | Hosted setup Checkout saved the test card. No immediate payment, no introductory trial and no lost free time; first payment began December 9, 2026 and bought a full month through January 9, 2027. |
| Cardless annual paid arrangement | Hosted setup Checkout saved the test card. No immediate payment and no lost free time; first payment began December 9, 2026 and bought a full year through December 9, 2027. |
| Deferral acknowledgement lost after Stripe applied it | Initial response was pending. Reload recovered one month, one subscription and the accepted target, with no additional nonzero invoice. |
| Former subscriber with a saved card | Cardless redemption created no new subscription or payment. Disabling the redeemed code kept granted access. Exact expiry returned to the Paywall without a new introductory trial. |
| Unpaid invoice | Preview returned 409, granted no access, left paid coverage unchanged and consumed no redemption. |
| Incompatible provider schedule | Preview returned 409, granted no access, left paid coverage unchanged and consumed no redemption. The schedule was a test fixture, not an implementation fallback. |
| Exact application horizon | A paid monthly subscriber starting March 1, 2028 accepted 23 free months after existing paid coverage, ending exactly March 1, 2030: 730 days from provider time. Original allowance/reset and invoices remained unchanged. An extra month returned 409 without consuming its coupon. |
| Hosted Checkout abandonment and retry | Leaving setup Checkout retained free time and created no subscription. Continue checkout reopened the same session; Cancel signup expired it, then a newly accepted offer opened a different session without a duplicate subscription or shortened access. |
| Exact provider horizon | Both modes accepted provider time plus `730 * 86400` seconds and rejected one second later. Repeating after advancing a day retained that same relative limit. |
| Gateway interval changes | Both directions in both modes retained the exact trial end and anchor without a new nonzero invoice. |
| Update arriving after the accepted payment date | Both modes refused the stale date and retained the already-paid interval, price and invoices. |
| Update one second before the accepted payment date | Both modes retained the date, added no immediate nonzero invoice and began a full paid month at that boundary. |

The original opt-in provider suite passed 16 cases. The corrected gateway/date-boundary cases passed another eight: four direction/mode combinations, two expired-date refusals and two last-second renewals. These are separate recorded invocations, not one claim that a single command ran all 24 together.

The ordinary pre-correction suites passed `make check`, 2,456 backend tests and 1,084 frontend tests. The corrective gateway/recovery suite passed 123 tests, including legacy/new request-policy recovery. Final branch CI supplies fresh full-suite results. The local Emulator browser baseline also passed four coupon journeys and ten additional checks, but does not replace these real-provider observations.

## Classic interval correction and replay compatibility

Stripe's classic-mode interval update rejected `billing_cycle_anchor=unchanged` with: "Changing plan intervals. There's no way to leave billing cycle unchanged." The failed app operation was a definite first-dispatch refusal, and its provider snapshot remained unchanged.

An isolated probe established that omitting that parameter preserves the existing trial-end anchor without a nonzero invoice. New application intents now persist a request policy and send the exact accepted `trial_end`, item price, no-proration setting and attribution metadata. Repeating the accepted date also makes a delayed request fail at Stripe if that date has already passed, instead of resetting an already-paid interval. Provider readback must still confirm attribution, the price, trial end and anchor before success.

Older intents without the new policy replay their original explicit anchor parameter under the original idempotency key. No database migration, changed API version or schedule is introduced. A refused old intent can review a fresh offer; an unresolved old write retains its existing recovery guard.

## Portal transition evidence

The app's explicitly configured management-only portal exposed payment-method/invoice management and no subscription-change, cancellation, resumption or Subscribe now controls in the observed session.

A separate owned legacy configuration initially exposed Update subscription and Cancel subscription. Disabling both features and its public login removed those actions from the refreshed old session. The old public login URL then displayed "The link you tried is no longer active."

An already-open cancellation confirmation, prepared before that restriction, returned HTTP 400 after restriction; the provider cancellation timestamp stayed unchanged. **An already-open annual price confirmation still returned HTTP 200 and changed the monthly price after the same restriction.** Its `continue_trial` setting retained the free end and added only a zero-value invoice. This disproves immediate revocation of all outstanding confirmations; it does not establish an immediate-charge exploit. [#430](https://github.com/pumpkit-io/pumpkit/issues/430) records the required corrective transition. This is evidence about the tested configuration transition, not a claim that merely changing Pumpkit's configured portal ID revokes other configurations or every existing session. The Operator must inventory every applicable old configuration and public login, disable unsafe actions there, and verify the actual transition before activation. Shared or live configurations were not changed by this run.

## Reproduce

The provider harness is opt-in and refuses live-mode credentials before creating resources:

```sh
cd backend
PUMPKIT_STRIPE_TEST_KEY=<test-mode-secret> uv run --extra dev pytest tests/billing/test_stripe_deferral_live.py -q
```

Supply the key through a private environment, not shell history or a committed file. With no explicit variable, every provider case skips; ordinary tests never acquire a real provider dependency. Each fixture deletes its test clock and archives its own product/prices.

To repeat app verification, use a disposable linked worktree and isolated database with coupons enabled, test-only billing credentials/catalog, the explicit restricted portal and signed test webhooks. Couple only that app's `get_clock` dependency to the current test clock. Start, inspect and stop it through its `scripts/dev-stack` contract; a human-authorized Stripe test run replaces the local Emulator only in that disposable copy. Keep publishing, SMTP and analytics off. Issue recipient-bound coupons through the privileged CLI; confirm through the real app, retrieve provider truth, then advance the clock through the accepted date. Do not infer success from a displayed Checkout page or a direct API-created subscription.

## Authenticated Dashboard inspection

The existing signed-in Chrome Dashboard was inspected read-only in both the live Pumpkit account and Pumpkit sandbox. The test API account matched the selected sandbox. No settings were saved and no test email was sent.

Both accounts had **trial-ending reminders** and **upcoming-renewal emails off**. Expiring-card and failed-payment emails and the trial-ending statement descriptor were also off. The upcoming-invoice event lead time was seven days; that event setting does not establish email delivery.

The generic trial-ending preview describes a trial ending on a sample date, a saved Visa card charged the recurring amount unless cancelled, and an update-payment-method link. Calling coupon access a trial misstates the independently agreed deferral. Keep this generic reminder off as found until applicable wording accurately identifies free access, the accepted future payment date/amount and cancellation rights.

The generic renewal preview describes automatic renewal on a sample date and a saved card charged then, with a payment-details update link. No explicit cancellation link was visible in that preview. These are generic example templates, not a delivered notice for a tested customer; cardless access must not imply a saved card or an arranged subscription. Operators and Self-hosters must establish appropriate notice wording and delivery before enabling such reminders. This run supplies no legal approval or proof of delivery.

The live portal configuration selector showed only Default. Its public login was inactive, but its preview still exposed cancellation. The sandbox Default likewise had no active public login. Shared configurations were left unchanged. An API inventory of all sandbox configurations and cleanup of owned fixtures is recorded separately; the live preview alone does not establish every historical link or outstanding session is safe.

Stripe [documents](https://docs.stripe.com/customer-management#features) a five-minute initial portal-session lifetime and expiry within one hour of its most recent use. An idle timeout does not by itself prove a fixed drain period: ongoing activity and already-open confirmations still need verification under #430.

## Remaining activation work

1. Resolve #430 with a demonstrated transition for outstanding sessions, applicable configuration/login inventory and safe reopening procedure. Restricting a configuration or selecting a new ID is insufficient evidence of revocation.
2. Establish notices appropriate to the independently accepted renewal and cancellation rights. The inspected generic reminders are off and are not evidence of delivery or suitable coupon wording.
3. Merge the #429 correction, pass required review/CI, retain the default-off setting, and close #394 only after its remaining acceptance criteria are evidenced. This report does not authorize live activation.

Provider references: [test cards and test-mode funds](https://docs.stripe.com/testing), [Billing test clocks](https://docs.stripe.com/billing/testing), [automated UI testing limitations](https://docs.stripe.com/automated-testing), [portal configurations](https://docs.stripe.com/api/customer_portal/configurations/update), and [trial messaging](https://docs.stripe.com/billing/subscriptions/trials/manage-trial-compliance).
