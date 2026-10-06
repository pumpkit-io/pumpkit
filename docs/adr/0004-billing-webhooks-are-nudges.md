# Billing webhooks are nudges; Stripe is read for the truth

A Stripe webhook only tells Pumpkit which customer changed. On every Subscription event and every completed Checkout, Pumpkit asks Stripe for that customer's Subscriptions (all of them, Ended ones included) and syncs its own copy from the answer, ignoring the event's payload. Checkout does the same sync before deciding whether the User may subscribe and gets a Trial. Stripe delivers webhooks out of order and late, so a copy built from event payloads let a late `updated(active)` revive a cancelled Subscription, and a Checkout started before a webhook landed could open a second Subscription or a second Trial. Reading the current state costs one Stripe call per event and per Checkout, and that cost is accepted. Don't "optimise" back to applying payloads.

## Considered Options

- **Compare event times and drop older events.** Stripe's event timestamps are whole seconds, so two changes in the same second can't be ordered, and it does nothing for the lag before a webhook arrives.
- **Never overwrite an Ended Subscription.** Kept, but only as a check that guards against bugs: on its own it doesn't fix `past_due` and `active` arriving swapped.
- **Fetch from Stripe before opening the webhook's database transaction.** Two webhooks for one customer routinely arrive together, and whichever wrote last could write the older state.

## Consequences

The webhook's transaction locks the User's row and holds it across the Stripe call, so webhooks for one customer run one after another. This reverses the earlier rule of no network call inside the webhook transaction, and matches what Checkout already does.
