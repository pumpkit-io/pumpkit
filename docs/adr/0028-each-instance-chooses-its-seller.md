# Each Instance chooses its seller

Whoever runs an Instance that sells Plans chooses who the seller is. By default the Instance is the seller: Checkout charges VAT through Stripe Tax, collects VAT IDs, and the Self-hoster or the Operator files the tax. With `STRIPE_MANAGED_PAYMENTS=true`, every Subscription and Top-up Checkout turns on Stripe's [Managed Payments](https://docs.stripe.com/payments/managed-payments/how-it-works), and Stripe, through Sold through Link, LLC, becomes merchant of record: it calculates, collects and files VAT, handles disputes and fraud, and sends receipts and invoices. pumpkit.io uses Managed Payments, so INCEPTIONAL S.R.L. invoices Sold through Link once a month instead of handling OSS, SdI e-invoices and foreign VAT registrations itself.

Seller mode stays the default because Self-hosters were promised they stay the seller of their own Instance, and upgrading must not change who owes their tax. Until this decision, every Checkout sent `managed_payments[enabled]=false` for that reason.

The billing gateway is the only code that knows the mode. In Managed Payments mode it sends `managed_payments[enabled]=true` and leaves out `automatic_tax`, `tax_id_collection` and `customer_update`, which [Stripe refuses](https://docs.stripe.com/payments/managed-payments/update-checkout#remove-unsupported-parameters) alongside it. Mediators and services do not branch on the mode.

## Consequences

- A Subscription keeps the mode of the Checkout that started it. Stripe applies Managed Payments only to Subscriptions started through a Checkout with it on, and authorizes the customer's payment method for that mode only. Switching an Instance's mode leaves existing subscribers in the old one until they go through Checkout again, so pumpkit.io switches before its first paying subscriber.
- Under Managed Payments each Plan's and the Top-up's product needs a [tax code Stripe accepts for it](https://docs.stripe.com/payments/managed-payments/eligibility#eligible-tax-codes). Pumpkit does not check this; Stripe refuses the Checkout and the gateway logs Stripe's reason.
- Managed Payments forbids Subscriptions created outside Checkout and has no setup-mode Checkout. This narrows ADR 0022's paid-signup mechanics: a paid Subscription a User arranges after Free access starts from one subscription-mode Checkout with `subscription_data.trial_end` at the agreed first payment date, in both modes, instead of a setup-mode Checkout followed by `subscriptions.create`. Stripe requires that `trial_end` to be at least 48 hours away. ADR 0022's promises (no immediate charge, no lost free time, the agreed payment date) stay.
- Updates to existing Subscriptions keep their calls: `trial_end` for Coupon deferral and Subscribe now, a price change with no proration for monthly and annual changes, and `cancel_at` for cancellation. Stripe's documentation neither allows nor forbids them on Managed Payments Subscriptions, so pumpkit.io turns the setting on only after they pass in test mode. A refused update surfaces as an error and changes nothing in Pumpkit.
- The Operator's Terms and Privacy Policy name Sold through Link as seller for payments. A Self-hoster who turns Managed Payments on updates their own the same way.

## Considered Options

- **Managed Payments always on.** Simplest for pumpkit.io, but it would make Stripe the seller on every self-hosted Instance at upgrade, against what Self-hosters were promised, and Stripe refuses products without an eligible tax code.
- **Managed Payments per Checkout**, for example by customer country. Stripe's mode is fixed per Subscription, so a mixed Instance would be both seller and not, with tax filings for one group of customers and Stripe's for the other.
- **Staying the seller on pumpkit.io.** It keeps Stripe Tax but leaves the Operator with OSS filing, one SdI e-invoice per Italian business customer, the esterometro and foreign VAT registrations, such as the UK's.
