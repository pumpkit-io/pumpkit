# Top-ups are the one thing sold outside a Subscription

Each Subscription gives an Allowance per Allowance period: 500 Generations and 100 X posts on pumpkit.io, at most 10 of them with a link, and a quarter of that for a 7-day Trial. A User who uses it up before the period ends can buy a Top-up: one fixed pack, €10 for 250 Generations and 50 X posts, at most 5 of them with a link. This narrows ADR 0003, which billed only by Subscription. We chose a pack over a second, bigger Plan because the Users who run out are few, and a pack covers them without a choice of Plan at checkout or a Plan change mid-period.

The numbers follow from cost. A Generation costs about $0.0025 in model calls ($0.015 in the heaviest case we estimated), an X post $0.015 to publish, and one with a link $0.20. The link price is why link posts have their own limit: 100 of them would cost more than a month of the Plan brings in.

## Rules

- A Top-up is spent only after the Allowance of the period in question is used up. It stays for 12 months from purchase, and only a Subscribed User can spend it. When a Subscription ends, what is left waits for the next one.
- Only a User whose paid Subscription is paid up may buy one: not in a Trial, where the offer is to start paying, and not while behind on payment.
- One fixed pack, bought by hand. No pack sizes and no automatic reload.
- A Top-up is never cheaper per Generation than the Plan (€0.040 against €0.038), so subscribing stays the better deal.
- Its Checkout asks for the same Terms acceptance as a Subscription's (ADR 0010). Once any of it is spent there is no refund. A refund or dispute through Stripe removes whatever is left.
- The one-off purchase flow ADR 0003 deleted stays deleted. A single fixed pack needs none of its catalog.

## Considered Options

- **A second, bigger Plan.** No one-off payments, but every User would have to choose a Plan up front, and a User who runs out once would have to change Plans mid-period.
- **Restoring the deleted one-off flow.** It already handled refunds and disputes, but it was a general product catalog with a known bug in its dispute handling, built for products that never existed.
- **Top-ups that expire with the period.** Simpler to count, but the User loses what they paid for.
