# Draining Checkout before changing seller

This is a privileged operator command, with no public HTTP endpoint. It preserves existing subscriptions and free access. It never cancels subscriptions or restores a database over payments. Keep general purchases paused until the final activation review, including the actual Link/provider races and Dashboard policy readback, has passed.

## Runtime and command contracts

`python -m pumpkit.billing.runtime_config` keeps schema version 1. Purchase-pause contract **3** covers `subscription`, `top_up` and `arranged_paid_signup`, and adds `durable_checkout_dispatch: 1` and `checkout_drain: 1` inside `purchase_pause`. The existing root `verification_user` object is unchanged. A configured paused fresh probe is not an execution barrier for an older worker.

`python -m pumpkit.billing.checkout_drain preview|execute|status|release` emits JSON with `schema_version: 1` and `capability_version: 1`. Exit 0 means `ready: true`, or `released: true` for release; otherwise exit 1 means unresolved. Output contains opaque local/provider IDs, counts through the listed arrays, fingerprints and blocker codes. It contains no Checkout URL, email, key or raw provider payload. Keep even these redacted reports protected.

- `preview` reads account-wide paginated open Checkouts, exact retained IDs and local operations. It changes neither the provider nor the fence.
- `execute` requires the full pause and no selected verification user. Its first invocation closes registration and returns the binding, while remaining unready until evidence is supplied. It commits the closed fence before taking any User lock or making provider calls.
- Supply `--evidence /protected/evidence.json --reviewed-evidence-sha256 <sha256-of-exact-reviewed-bytes>` to execute or status. Execution resolves registered original dispatches, expires only proven owned old seller-mode sessions, re-reads current state after success or expiration error, and syncs actual completed purchases. Repeat the command to resume. Pending benefits, accepted signup dates and cancellation intent remain authoritative; unresolved operations block readiness.
- `status` rechecks provider state, the journal, pending operations and the current binding. It cannot manufacture a receipt. A prior receipt becomes unusable when the configuration, fence, generation, evidence or inventory no longer satisfies the contract.

The source binding contains `instance_id`, `generation`, `config_fingerprint`, `account_id` and `livemode`. Execute also reports `current_config_fingerprint`, `fence {closed,generation}`, `blockers`, `proposed_expirations`, `expired`, `completed`, `unknown`, `unresolved_dispatches`, `pending_operations` (opaque kind/ID pairs), `last_release`, `ready` and `receipt`. An empty provider listing never establishes readiness by itself.

## Protected reviewed evidence

The public application has no dependency on an ops repository. Its trusted input boundary is a protected reviewed file passed explicitly by an operator with Instance command access. This is an evidence protocol, not an automatic certification of historical completeness. An independent reviewer must inspect the actual legacy creator and provider request population before supplying its exact digest. Hashing an incomplete file does not make it complete.

The file uses this schema (all example references must be replaced by actual reviewed records):

```json
{
  "schema_version": 1,
  "binding": {
    "instance_id": "from-execute",
    "generation": 1,
    "config_fingerprint": "from-execute",
    "account_id": "from-execute",
    "livemode": false
  },
  "pause": {
    "release": "exact-release-and-revision-reference",
    "image": "exact-immutable-image-reference",
    "operation": "pause-operation-and-config-evidence-reference",
    "creator_evidence": {
      "backend": "old-and-replacement-worker-identity-and-request-boundary-reference",
      "publisher": "old-and-replacement-identity-and-request-boundary-reference",
      "coupon-maintenance": "old-and-replacement-identity-and-request-boundary-reference",
      "recovery-cli": "complete-one-off-process-population-and-request-boundary-reference"
    }
  },
  "legacy": {
    "completeness_evidence": "review-of-complete-applicable-creator-and-request-population",
    "no_applicable_dispatch_evidence": "positive-evidence-if-requests-is-empty",
    "requests": []
  },
  "review": {
    "operator": "operator-review-identity",
    "reviewer": "different-independent-review-identity",
    "record": "protected-approved-activation-record-reference"
  }
}
```

Each nonempty `legacy.requests` entry has `request_reference`, `creator` (one of the four creator keys), `parameters_sha256` (64 lowercase hex characters), `relationship_evidence`, `outcome_evidence`, `outcome` and optional `session_id`. The reviewed request parameters, exact customer/User/operation relationship, original provider idempotency reference where available, and provider response are retained behind those references. Outcomes are `object` with the exact resulting Session ID, `execution_not_started` with specific positive rejection evidence, `provider_resolved_no_object` with specific provider-supported resolution, or `unknown`. Unknown entries fail. Every named object is independently retrieved and must satisfy current ownership/state checks; a manifest cannot override a contradiction. A generic 4xx, a cached 500, timeout, absent log, elapsed interval, deployment or empty listing does not establish a resolved request. Escalate unresolved historical requests to provider support. Manual completeness and Dashboard request inspection remain mandatory in final activation verification.

New sessions require a consistent journal, Instance/dispatch/kind metadata, customer, immutable User reference, purchase mode, seller and original return routes. Historical ownership requires surviving authoritative customer/User or exact Session relationships plus the recognized mode/routes; paid signup also requires its exact retained operation marker. Missing relationships, detached/deleted customers and contradictory metadata remain unknown. Clearly foreign return origins with no local claim are excluded. Unknown sessions are left untouched, including the two unattributed sandbox sessions recorded in the customer-action evidence.

## Dispatch and fence lifecycle

All three creators persist the exact original CREATE parameters and idempotency key before any provider dispatch. Those include seller options, customer, price, quantity, trial fields with their omission preserved, expiry, metadata and return URLs. Paid signup retains its internal PaidSignup ID separately from the client's retry ID. Terms evidence stays local. User deletion blocks unresolved dispatches in both deletion branches; resolved journal rows cascade with the User.

Registration and closing the Instance fence serialize on one short database transaction. After committing intent, the original caller reacquires the User lock and reloads its journal before entering the provider. Drain resolves under that same User lock. If drain wins the committed-intent gap, the old caller sees the resolved record and cannot send. If an original provider call already owns that lock, drain returns an unresolved result after bounded lock contention. No global fence lock spans a User lock or network call. PostgreSQL contention tests exercise these orderings.

An unresolved dispatch may be replayed only by explicit execute, with its original pinned parameters and original key, before 24 hours from recorded dispatch intent. This may create the original object, so it is controlled reconciliation work rather than evidence of absence. The cached response is followed by an exact current GET. A 500 or timeout stays unknown; after the guaranteed key-retention window, do not retry with a fresh key or assume no object exists. Ordinary paused request/recovery paths never use this operator reconciliation exception.

The fence remains closed while ops switches the seller and selects a verification user. Readiness binds the **source** paused configuration. For the deliberate source-to-target handoff, run:

```sh
python -m pumpkit.billing.checkout_drain release \
  --generation <source-generation> --receipt <source-receipt> \
  --target-fingerprint <exact-current-target-fingerprint> \
  --evidence /protected/evidence.json --reviewed-evidence-sha256 <reviewed-source-evidence-sha256>
```

Release requires the same still-closed generation and stored receipt/evidence, the same non-policy configuration, a recorded source seller policy, and a current target with Managed Payments enabled (or the fully paused pre-cutover abort described below). Only the seller/pause/verification selection may differ from source. Both disabled-to-enabled cutover and enabled-to-enabled verification cleanup or reopening are supported. It rechecks inventory and unresolved operations, consumes the receipt and increments generation before opening registration. `current_config_fingerprint` is available even when status correctly rejects the intentionally changed target as source readiness. Ops must verify the selected user through the runtime probe and enforce its final paid-check/general-reopening policy before this explicit handoff. Reopening registration does not override the normal purchase pause or eligibility checks. A receipt cannot release a later generation. An exact retry can acknowledge its already committed consumption, as described below. There is no generic unlock flag or permanent extra pause.

## Upgrade notes

This is a one-time boundary when moving from pre-journal code to contract 3. It is not a purchase pause required on every later contract-3 upgrade.

1. Pause purchases and clear the verification selection in the canonical protected environment. Confirm the complete old pause where supported; do not change seller.
2. Stop **all old Checkout-capable creators before migration 0069**: backend workers, publisher, maintenance/recovery workers, scheduled commands and one-off recovery processes. Record the actual old process population and its possible provider requests. Stopping a process does not prove a delivered request had no remote effect.
3. Ensure `BILLING_PURCHASES_PAUSED=true` and `BILLING_VERIFICATION_USER_ID=` are canonical **before any upgraded creator or new acceptance starts**, then apply 0069 and start only the upgraded release. Do not overlap old and new creators. New accepted signups explicitly record their creation contract atomically with acceptance; older rows and older writers default to legacy. An old process can still read a newly marked row and ignore the journal, so neither the marker nor migration proves quiescence.
4. Verify every replacement creator's contract-3 runtime readback and actual process identity. Review all one-off processes too. Keep full pause with no selector through the independently reviewed legacy request/worker evidence and owned-session reconciliation. Migration, deployment, a fresh probe, elapsed time or an empty listing cannot supply that proof.
5. Resume the closed-fence operation with its exact binding. Missing original parameters or unresolved historical requests remain unverified and may require provider support. An absent legacy paid signup cannot mint a current-parameter replay, age a new idempotency window, cancel from absence, expire from a clock or bypass either deletion branch.
6. Consume the reviewed receipt through the supported release lifecycle. A self-hoster keeping seller mode can release only the extra fence while the full pause remains active, then finish their maintenance reopening policy. A seller transition still requires its separate final activation gates before general reopening.

Existing observed provider objects continue ordinary reconciliation. Subscriptions, accepted dates, cancellation intent and free access are preserved; old Subscriptions are never migrated. The public application depends only on the explicit protected evidence protocol, not on a private operations repository.

## Interrupted provider invocation

The adapter and dispatch owner wait for the actual SDK worker to finish when their async caller is cancelled. A raw task cancellation must not release the User lock while a sync worker can still enter CREATE. Both application and operator attempts retain a durable unresolved marker if their process or checkpoint is interrupted. Seeing a matching object or replay response cannot clear an invocation whose owner has not acknowledged completion.

For such an interrupted owner, or an indeterminate Stripe CREATE error, the protected evidence may additionally contain `dispatch_resolutions`. Each entry requires `dispatch_id`, the SHA-256 of the original parameters serialized as sorted-key JSON (`parameters_sha256`), the SHA-256 of the original key (`idempotency_key_sha256`), `worker_resolution_evidence`, `provider_resolution_evidence`, `outcome` and optional `session_id`. The outcome is `object` with an exact Session ID, or `provider_resolved_no_object` backed by positive provider resolution. The reviewer must establish that the original worker can no longer dispatch, and the original provider request has a resolved outcome. These are specific reviewed evidence references, never an unchecked “clear unknown” flag. The command matches both original fingerprints, current source binding and current object relationships. Unknown or unreviewable records stay blocked and may require provider support.

A completed Session also remains unready until its exact resulting Subscription or Top-up is visible and synchronized. A successful current Session GET does not replace the actual benefit/accepted-operation reconciliation. Repeated execution grants no duplicate benefits.

## Resuming after a compatible configuration change

When a release or unrelated configuration change invalidates a closed source binding, keep the newer configuration and start a fresh **closed** generation explicitly:

```sh
python -m pumpkit.billing.checkout_drain execute \
  --recapture-generation <expected-old-closed-generation> \
  --current-fingerprint <exact-current-config-fingerprint>
```

The command requires complete pause with no verification selection. It increments generation, invalidates the old receipt and evidence, retains every pinned dispatch, uncertain invocation and pending operation, and returns a new binding while remaining unready. Obtain fresh independently reviewed evidence bound to that generation before resuming execute. Wrong or stale generation/fingerprint fails closed. This never releases the fence or clears an unknown outcome.

For a pre-cutover abort, release also accepts a source and target that both have Managed Payments disabled, provided the target remains fully paused with no verification selection. It consumes the same reviewed readiness receipt and opens only the additional fence. It refuses an unpaused seller-mode abort and a Managed Payments-to-seller reversal. The normal pause remains authoritative, so abandoning a transition does not require a temporary seller flip or direct database unlock.


## Receipt checkpoint recovery

Ready and released results are emitted only after the database acknowledges their final checkpoint. A commit error or lost acknowledgement returns `ready: false`, no receipt and no `released: true`; it does not pretend to roll back a provider expiration. Resume execute or read status to reconcile the actual stored receipt and current provider state.

Release stores only the latest consumed opaque receipt, source generation, target configuration fingerprint and evidence digest. The report's `last_release` names that committed consumption. Retrying release with the identical receipt, generation, reviewed source evidence and unchanged exact target fingerprint returns `released: true` with `release_replayed: true`, without another mutation or generation increment. This acknowledges an already committed release; it never grants fresh drain readiness (`ready` remains false). It works after a commit succeeded but its reply was lost. A later closed generation or changed target rejects the old token. No account/customer identifiers are retained in this consumption marker.


## Legacy paid signup with a positive no-object outcome

A legacy pending signup remains pending when its Checkout is absent. Its old internal key is never retried with current settings. For a specific positively resolved original request, a `legacy.requests` entry may additionally supply `paid_signup_id`, `accepted_offer_sha256`, `idempotency_key_sha256` and `parameters` (the exact original full CREATE parameters). These fields are required together and only for `execution_not_started` or `provider_resolved_no_object`.

The command matches the immutable internal PaidSignup ID, canonical sorted-key JSON hashes of the original parameters and accepted offer, and SHA-256 of the original `${PaidSignup.id}:checkout` key. It validates the original subscription-mode price/quantity, customer/User, trial end, expiry, metadata, seller options and original Settings return URL against the accepted operation, without substituting current settings. It also reads current matching Checkouts and Subscriptions; a contradictory object blocks resolution. Unsupported setup/guest flows, missing original parameters and unreviewable requests stay unverified.

Only this bound reviewed no-object outcome may end the legacy accepted operation as refused, preserving its recorded offer/date and all free access. It does not re-enable the old key or create a replacement. A later purchase needs a fresh offer and acceptance. Existing observed objects use normal current-state reconciliation instead.

## Managed verification cleanup is a separate responsibility

This command expires proven-owned **seller-mode** Sessions. A managed open Session blocks a fresh receipt with `unexpected_managed_checkout`; enabled-to-enabled release does not automatically clean up an abandoned verification Checkout. An authorized operator must close only that exact proven-owned Session through supported Stripe expiry controls, or observe its natural expiry through an exact current read. Re-read after any expiry error and reconcile a completion race. Waiting an assumed interval is not proof, and no unknown request may be discarded. Existing arranged-signup cancellation remains available under its normal rules.

Managed completed Sessions are not a paid-control/access certificate from this drain. Ops and final activation verification must establish the actual paid Subscription, signed webhook, current application access and Allowance, and policy readback before general reopening. That proof belongs to the selected paid-control and final activation procedure, including the mandatory Link/provider race checks; a drain receipt cannot replace it.


## Proven rejection before Checkout creation

A fresh journaled CREATE disables SDK retries so an earlier uncertain attempt cannot be hidden by a later rejection. Only structured Stripe responses establish that execution never began: authentication failure (401), missing or unknown parameter validation (400 with `parameter_missing` or `parameter_unknown`), or a rate-limit rejection (429 with a documented `Stripe-Rate-Limited-Reason`). An `Idempotent-Replayed: true` response never establishes absence. These outcomes finish and settle the dispatch. An accepted arranged paid signup also ends as refused, preserving its offer, acceptance and Free access; the User reviews a fresh offer rather than replaying its old key.

A generic 400 or `InvalidRequestError`, including an invalid or archived price without specific preexecution proof, is insufficient. Stripe can retain errors after execution begins. Conflicts, lock timeouts, payment failures, server incidents and connection failures remain unresolved. A later replay's authentication, validation or rate-limit rejection cannot establish that an earlier invocation created nothing, so operator replay also retains uncertainty. Specific reviewed original-request no-object evidence can settle the dispatch and its arranged signup through the normal evidence contract.

If User locking or eligibility revalidation fails after intent commits but before CREATE starts, the request rolls back the failed transaction, reacquires the User lock and durably acknowledges no dispatch. A failed acknowledgement leaves the intent unresolved. Cancellation and process interruption never substitute for a finished-worker acknowledgement.
