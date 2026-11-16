---
status: accepted
---

# Changing seller preserves existing billing commitments

ADR 0028 chooses Managed Payments for pumpkit.io, while each Subscription keeps the seller it started with. Activating that choice is a controlled transition of future purchases: existing paid time, Free access, cancellation intent and agreed payment dates must survive both customer actions and operational recovery.

## Hosted billing management

Prefer the existing restricted Stripe customer portal if test-mode evidence proves it replaces the payment method used by the Managed Payments Subscription. Changing only the Customer's default card, opening a portal URL or returning to Settings proves too little. Verification includes a subsequent renewal or payment retry using the replacement card.

Pumpkit does not collect card details or try to assign a Managed Payments Subscription's payment method directly. Where a different destination is necessary, select it from the actual Subscription's mode rather than the Instance's current choice for new purchases. Keep the existing Settings layout, cancellation controls and pending-operation guards.

Link gives Managed Payments customers order-management actions independently of whether Pumpkit adds a link to it. Activation therefore requires evidence that both Link and the portal preserve ADR 0022's commitments. A provider limitation that breaks those commitments reopens the billing approach; redirecting the User elsewhere does not resolve it.

## Purchase transition and recovery

Use a narrowly scoped purchase pause while changing seller. It stops new Subscription, Top-up and arranged paid-signup Checkouts, while reads, webhooks, cancellation and recovery continue. A separately selected verification User may complete the controlled live check while general purchases remain paused. This grants no free access or exception to the normal payment and acceptance rules. Pausing purchases must not disable billing or turn the Instance into one that grants access without a Subscription.

Before the switch, drain in-flight Checkout creation, inventory the Instance's old open Checkouts and reconcile completed, expiring and pending operations. An uncertain provider result must be resolved before the transition proceeds. Expiration racing a completion must be reconciled against Stripe. Do not expire another Instance's or an unrelated application's sessions. Old Subscriptions are not migrated.

The ops approach is a small, backed-up configuration operation for the seller setting and purchase pause on an installed Release. It snapshots protected configuration before any edit, preserves unrelated settings, verifies affected services and records the outcome. A configuration failure closes new purchases and restores the previous configuration where safe, without restoring an older database over subsequent writes. Once a Managed Payments purchase exists, closing new purchases is the default recovery action; changing the setting back would create two seller populations rather than undo that purchase.

## Activation evidence

The existing-user notice population and effective date must be explicit. An absence of paying subscribers or checkout acceptances does not establish an empty notice population. Publication alone does not establish delivery. Notice evidence belongs in protected operational records, with a rule for failed delivery, changed contact addresses and Users joining during the notice period. The existing Terms' advance notice is preserved.

Confirm the refund policy, support contact and payment-update email destination against the verified customer journey. Adding payment methods is outside this activation; standard Stripe Dashboard switches are not evidence of Managed Payments method availability.

Complete one explicitly authorized paid purchase from the app before broad reopening. Record the seller shown, paid amount, provider Subscription mode, signed webhook result and Pumpkit's resulting access and Allowance. A Trial or expired unpaid Checkout does not establish a completed purchase. Read current provider state when reconciling, as ADR 0004 requires.

## Considered options

- Flip the environment setting on a normal deployment. Old Checkouts can still finish under their original seller, and the existing deployment backup follows manual configuration edits. This does not provide the required transition or recovery evidence.
- Use Link as an immediate card-replacement workaround. Its other customer actions still need verification against existing commitments.
- Build a general configuration management service. The operation stays limited to these billing settings; a wider platform is not needed for this transition.

Sources: [Managed Payments customer management](https://docs.stripe.com/payments/managed-payments/how-it-works#manage-orders), [portal flow targets](https://docs.stripe.com/customer-management/portal-deep-links), [Managed Payments payment-method configuration](https://support.stripe.com/questions/payment-method-configurations-for-managed-payments), [prior sandbox results](https://github.com/pumpkit-io/pumpkit/issues/493#issuecomment-6876632397). The current ops limitations are in the private `pumpkit-ops` deployment, server-apply and rollback scripts.
