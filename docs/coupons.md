# Coupon implementation and operations contract

This is the implementation contract for spec #392, settled by #396. Privileged issuance, recipient preview and cardless redemption are implemented. Subscriber extensions remain unavailable until their later tickets implement those rules. The public English and Italian documents describe the complete feature; publishing them does not activate it or constitute legal approval. Self-hosters supply their own legal documents.

## Activation and provider evidence

`COUPONS_ENABLED=false` is the one default-off feature setting. Off means no issuance, preview, redemption or coupon-specific paid signup/Plan-change actions and no coupon affordances. Ordinary billing and Instances that sell no Plans keep their existing behavior. Coupon functionality also requires configured Plans. Enable it only in isolated test environments until final #394 passes.

Implement #396, #395, #397–#405 in order with normal checks, fake-gateway tests, adapter contracts and PR review. Real Stripe validation runs only after their PRs merge. It is the activation gate, not an implementation prerequisite. Reuse `pro-coupons-t394`'s `backend/tests/billing/test_stripe_deferral_live.py` and `docs/stripe-coupon-verification.md`. Their partial evidence is historical and does not validate the merged application. Hosted Checkout through its first paid period and authenticated notice/configuration inspection remain outstanding.

The recorded experiment accepted an absolute `trial_end` of provider time plus 730 × 86400 seconds and rejected one second later, in classic and flexible modes. Include remaining paid time in this bound and apply it to cardless claims too. Preserve original paid/Trial coverage and Allowance anchors locally. A Stripe `trialing` deferral is not an introductory Pumpkit Trial. Existing `end_trial` charges immediately and must not consume free time. The recorded portal approach uses no proration and `trial_update_behavior=continue_trial`; respect the effective `cancel_at`, even when `cancel_at_period_end` is false. These are implementation inputs pending final verification, not permission to reduce benefits if a provider case fails.

## Acceptance contract

Terms version `2026-11-08` is shared by both languages and the backend. The Privacy Policy has the same update date, including the November 7 site-statistics disclosures. The existing paid Subscription and Top-up flows retain their three separate boxes and acceptance evidence. Every later paid signup requires new paid acceptance, including a future Subscription arranged during Free access. Having a saved card or Coupon acceptance is insufficient.

Coupon confirmation uses two unticked boxes. There is no paid immediate-start/withdrawal waiver and no new automatic-renewal acceptance. Clause numbers and anchors match the public documents:

1. English: “I accept the Terms and have read the Privacy Policy.” Italian: “Accetto i Termini e ho letto l’Informativa sulla privacy.” Link each document in the selected language.
2. English: “Under arts. 1341 and 1342 of the Italian Civil Code, I specifically approve clauses 9 (Suspension and termination by the Operator), 16 (Limitation of liability), 19 (Changes to these Terms) and 21 (Competent court).” Italian: “Ai sensi degli artt. 1341 e 1342 del Codice civile, approvo specificamente le clausole 9 (Sospensione e risoluzione da parte del Gestore), 16 (Limitazione di responsabilità), 19 (Modifiche ai presenti Termini) e 21 (Foro competente).” Link each clause. Do not include clause 12's automatic renewal or clause 14's paid refunds in this approval.

Before these boxes show the exact start/end, full monthly Allowance and next agreed payment, or “No automatic payment” / “Nessun pagamento automatico”. For a cardless recipient show “Free access ends on {date}. This creates no subscription or obligation to pay.” / “L’accesso gratuito termina il {date}. Non crea un abbonamento né un obbligo di pagamento.” A subscriber instead sees the preserved paid coverage and actual deferred payment under their existing renewal choice.

#398 records authenticated User, UTC acceptance timestamp, Terms version, language, both affirmative boxes, accepted preview/benefit dates, payment consequences and operation identity, associated with that redemption. `requested_immediate_start` is false if the existing acceptance model is reused. A Coupon-specific request must not require it to be true. Preview binds the displayed version and exact offer; confirmation revalidates both. Missing/false acceptance is refused without a claim or provider mutation; an old version or changed offer returns a conflict requiring a fresh preview and cleared boxes. Duplicate confirmation recovers its original result and evidence, never another benefit. An Instance without Operator details follows the existing no-Terms contract rather than fabricating acceptance.

#397 delivers preview and the shared form; #398 implements local redemption evidence; #401 extends the same evidence to durable provider operations. No sign-in acceptance or new MCP redemption tool is added.

## Identity and key custody

#395 stores recipient assignments as keyed fingerprints, with no plaintext recipient email. Normalize exactly as account creation does (`email.strip().lower()` after email validation); do not remove dots or plus suffixes. Claim identity uses the same verified email normalization in #398. Include a purpose separator and Coupon identifier in HMAC-SHA256 inputs so fingerprints for unrelated Coupons cannot be linked without the key. Store a key identifier with every fingerprint. Code digests are separate from email fingerprints; raw codes appear once in intentional CLI output, never in logs, URLs or analytics.

`COUPON_IDENTITY_KEYS` is a secret JSON key ring: `{"active":"v1","keys":{"v1":"<base64 of 32 random bytes>"}}`. #395 validates it before enabling issuance. The active key writes new fingerprints. Matching evaluates every retained key so a new active key cannot reset an old claim. Retired keys remain available for matching until no retained assignment, claim or unresolved operation needs them, and their last containing backup has expired. Do not try to rehash old fingerprints without the verified email. An absent referenced key fails closed for affected operations and alerts the person running the Instance; it never treats the identity as unclaimed.

Keep the key ring in the Instance secret store, restricted to its application and privileged tooling. Back it up encrypted separately from the database, with access restricted to the same trusted people. Restore the database and its corresponding complete key ring together. Test recovery before rotation. Rotate by adding a new unique key identifier and making it active, retaining old keys for reads; never replace a key's bytes in place. A no-deadline Coupon can require its old key indefinitely. To retire a compromised key, permanently disable affected unclaimable/claimable codes as appropriate, resolve all operations and preserve existing benefits, then wait out record and backup retention before removing it. Key loss is not repaired by resetting claim eligibility; restore it or keep affected operations disabled.

## Retention and purge

These periods implement purpose limitation rather than applying the tax retention period to all Coupon data. Fingerprints remain pseudonymous personal data. The choices implement the product's same-email claim promise while limiting ended-benefit and recovery history. They are product retention decisions, not a claim of legal approval. The [GDPR's storage-limitation and lawful-processing rules](https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32016R0679) inform the contract.

A Coupon becomes permanently unclaimable at its UTC deadline, permanent disable, or exhaustion by completed claims with no pending reservation that can restore capacity. Store this terminal time; disabling is irreversible. Pending operations still need reconciliation. Turning the feature off is temporary and does not terminate redeemability for retention purposes.

| Record                                              | Retain until                                                | Purge behavior and owner                                                                                                                                                  |
| --------------------------------------------------- | ----------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Unclaimed recipient assignment                      | Permanently unclaimable and all related operations resolved | Remove fingerprint/key identifier within 30 days; #395. No-deadline codes retain their assignment while claimable.                                                        |
| Claim fingerprint, including after account deletion | Same terminal condition                                     | Remove within 30 days; #398. Keep a nonpersonal completed-claim count so purging cannot restore capacity.                                                                 |
| Active/queued benefit and its acceptance            | Benefit end and resolution of related operations            | Remove within 90 days of the later event; #398. Account deletion ends benefits and removes the account link immediately, retaining only required claim/recovery evidence. |
| Pending recovery intent/evidence                    | Confirmed reconciliation or definite refusal                | Never age out unresolved work; #401. Keep only stable operation/provider identifiers, accepted offer, target and original coverage facts needed for recovery.             |
| Resolved recovery/audit evidence                    | Resolution and end of related benefits                      | Remove within 90 days of the later event; #401. Do not keep raw provider payloads or recipient email.                                                                     |
| Backups containing removed data or old keys         | Last live removal                                           | Existing rotation removes copies within 30 days. Reapply purge after restore before serving traffic.                                                                      |

Where one row serves several purposes, remove unnecessary fields independently and retain only fields whose purpose remains. Account deletion detaches the User but preserves claim fingerprints and the minimum unresolved billing evidence. It must serialize with redemption/recovery and must not allow later recovery to grant orphaned access or charge a deleted account. A pending operation keeps enough deletion intent to finish safely; it does not retain the deleted profile or content. A legal hold must be separately justified, documented and limited to its actual records, not silently applied to every Coupon.

#395 supplies privileged `uv run python -m pumpkit.billing.coupons purge` from `backend/`; #398 and #401 extend that command for their records. Run it daily with the same Instance configuration and database privileges, including when `COUPONS_ENABLED=false`. It must be idempotent and safe against concurrent claims, disable and recovery, with the same lock order as redemption. Inspect its nonsecret counts and failures; retry a failed daily run immediately. Check unresolved operations daily, flag anything pending more than 24 hours and investigate until resolved; there is no destructive age-based timeout. #401 supplies the independent recovery invocation and its lock order. Do not log keys, codes, email assignments, fingerprints or full provider responses in purge/recovery output.

## Upgrading and self-hosting

#395 introduces the setting, key ring, migration and executable issuance/purge commands. Leave the setting off outside isolated tests until the later implementation slices are installed and #394 is complete. At that point, install a daily purge/recovery job, back up the complete key ring securely with the database recovery process, replace the legal documents for your Instance and verify the disabled setting before starting it. Each runtime ticket adds its applicable Upgrade notes. An Instance selling no Plans needs no Coupon key or job.

Publishing these changed legal documents does not send the material-change notice promised in clause 19. The Operator must arrange that notice before applying a material change to existing Users; this PR sends no email. Self-hosters follow their own notice obligations and bump the frontend/backend Terms dates together when replacing the documents.

## Privileged Coupon commands

The commands run with the Instance's database and application configuration; they have no public endpoint. Access to the source alone does not allow issuance. Run migrations before using them. Each code is 32 cryptographically random bytes encoded for copying. The database stores its SHA-256 digest, never a recoverable code; recipient assignments use the keyed fingerprints above. Issuance metadata and benefit months cannot be changed through this tool.

Generate each identity key with `openssl rand -base64 32` in a trusted terminal and insert it in the protected JSON ring. Keep the output out of shared logs. Coupons must stay off outside isolated tests until final validation.

On a compose Instance, use its configured backend:

```sh
docker compose exec backend python -m pumpkit.billing.coupons create --months 3 --recipient recipient@example.org --max-redemptions 1 --claim-deadline 2027-12-01T00:00:00Z
docker compose exec backend python -m pumpkit.billing.coupons list
docker compose exec backend python -m pumpkit.billing.coupons inspect coupon_ID
docker compose exec backend python -m pumpkit.billing.coupons disable coupon_ID
docker compose exec backend python -m pumpkit.billing.coupons purge
```

For a managed database outside compose, export the same protected Instance settings, then run `uv run python -m pumpkit.billing.coupons ...` from `backend/`. Alternatively `uv run --env-file ../.env python -m pumpkit.billing.coupons ...` explicitly loads the root configuration. Do not point a development command at production accidentally.

Create requires positive whole `--months`; `--max-redemptions` defaults to one. Omit `--recipient` for a general code and `--claim-deadline` for no deadline. A deadline must have a UTC offset (`Z` or `+00:00`) and be strictly in the future. Recipient normalization matches sign-in: trim whitespace and lowercase the validated email, retaining dots and plus suffixes. Unsupported future horizons are refused later at preview/confirmation rather than silently shortening benefits.

Successful create prints one JSON object with `id` and the raw `code`. Deliver that code privately once. Avoid terminal recording, CI logs, redirected shared files and analytics. Losing it requires a new code; inspect/list cannot recover it. All other commands use the nonsecret `id` and never print the code, assigned email or fingerprint. Nonzero exit status means failure, with a sanitized explanation on stderr; a failed transaction prints no code.

Disable is permanent and idempotent. It stops new claims and leaves existing benefit records intact when redemption is implemented. Inspect, list, disable and purge remain available while the feature is off so Operators can maintain existing records. Purge removes recipient fingerprints and their key identifiers at 30 days after permanent disable or deadline, preserving the restricted-recipient marker and immutable metadata. A still-claimable code without a deadline retains its assignment. The claim/recovery tickets extend purge for their additional records and pending-operation safety.

Run purge daily using the same protected settings, including while Coupons are off. A cron/systemd job can invoke `docker compose exec -T backend python -m pumpkit.billing.coupons purge` from the Instance directory. Check its nonsecret count and exit status; retry failures immediately. Current management locks Coupon rows in identifier order, with purge skipping busy rows for the next run. Recipient redemption/recovery will follow User, then Coupon, then operation lock order; disable and purge never acquire a User lock after a Coupon lock.

**Upgrade notes:** The migration adds only the Coupon table. Existing Instances need no key while the default setting stays off. Before isolated testing or eventual activation, configure and securely back up the key ring and install the daily purge job. Follow final #394 before enabling outside isolated tests. Already-issued codes require their matching database and complete key ring through upgrades and restores.

## Recipient preview

With Coupons enabled in an isolated test Instance, the Paywall offers **Have a coupon?** before paid checkout, including when a payment is on hold. **Check code** sends the code in an authenticated request body to `POST /api/v1/billing/coupons/preview`; it never puts it in a URL or analytics. Checking a code previews the offer without consuming it; the separate confirmation grants access.

Preview requires an available code, its verified recipient where restricted, compatible configured offers and a supported billing state. It checks current provider Subscriptions and all customer invoices, so an older outstanding invoice cannot be hidden by a newer paid one. Pending changes, unsettled invoices and unsupported existing-Subscription paths are nonconsuming refusals. No customer, Subscription, claim, capacity reservation or access is created. Provider failures retain the code in the form for retry.

The response supplies UTC start/end timestamps, whole calendar months, the full monthly Allowance, payment consequences, the applicable Terms version and a signed `revision`. Benefits beyond 730 × 86400 seconds are refused before calendar overflow is possible. Month calculation uses the original anchor rather than adding clipped month ends successively.

The revision uses the existing Instance JWT signing secret with a separate `coupon-preview` salt. It authenticates the caller and Coupon identifiers, displayed offer and preview instant, plus a digest of the issuance/recipient state. It contains no raw code, recipient email or fingerprint. Its payload expires ten minutes after preview. #398 must verify signature, expiry, caller and Coupon identity, then recheck current availability, recipient, billing eligibility, offer/Terms and horizon before confirming; a changed offer requires a fresh preview and acceptance. Merely advancing the clock does not corrupt the authenticated original preview instant. A preview reserves neither its dates nor capacity. Rotating the JWT secret invalidates outstanding previews, which can safely be checked again.

## Cardless confirmation and access

Cardless redemption accepts a recipient with no running Subscription or pending paid Checkout, including someone with remaining Free access. Subscriber extensions remain nonconsuming refusals until their later tickets. A former subscriber with a settled account can redeem without using their saved card. Confirmation reads provider eligibility under the User billing lock and creates no Stripe customer, Subscription, Checkout or payment. An open paid Checkout must finish, expire or be cancelled by support before redemption; checking or refusing a Coupon does not cancel it.

For an immediate cardless offer, the Paywall says **Starts when you redeem** and displays UTC calendar dates. Preview timestamps describe those dates; their seconds are not an already-running grant. The signed revision binds the months, displayed UTC dates, full monthly Allowance, payment consequences, Terms and issuance state. Confirmation anchors the whole calendar-month interval at its current server time, after lock waits and provider checks. It requires a fresh preview if either displayed UTC date changed, or if any other offer term changed. This preserves full usable months without treating every elapsed second as a changed offer. The final result contains precise UTC timestamps. A January 31 anchor resets on February's last day and then March 31, calculated from the original anchor.

`POST /api/v1/billing/coupons/redemptions` accepts a caller-generated operation identifier, signed revision, language and the two cardless acceptance boxes above. It accepts no client dates, email or month quantity. The signed-in caller can recover the committed result with `GET /api/v1/billing/coupons/redemptions/{operation_id}`. Repeating the same operation and revision returns its original dates, including after disable, preview expiry or temporary feature deactivation. Reusing an identifier for another revision is refused. Keep the same identifier after a lost response. Result lookup and acceptance evidence remain available until the benefit's 90-day post-end purge; they are removed immediately on account deletion.

The User row is locked and freshly rechecked for existence and suspension, followed by the Coupon row, then its claim and operation records. Disable locks only the Coupon. Under that lock, identity matching checks every retained claim key before inserting an active-key fingerprint. Claims have a database uniqueness constraint, each benefit has one unique claim and each caller has unique operation identifiers. Benefit, accepted offer, count and result commit together. Exhaustion records a permanent terminal time. No pending provider operations exist in this local-only path; #401 must extend the deletion and purge owners before introducing them.

Free access remains effective when Coupons are temporarily disabled. Billing status, Onboarding, browser and Connected app access and the publisher use the same half-open interval: access ends at the precise end timestamp. Monthly Allowances use the accepted full caps, including existing Top-ups under their ordinary spending rules. Scheduling projects from the original anchor and refuses publication at or after the known end. New paid signup is refused during remaining Free access until #404 can preserve it; Top-up purchase during Free access arrives in #400. A minimal account-bound history marker removes introductory Trial eligibility after detailed benefit evidence is purged.

Purge now reports `records_purged`, counting recipient assignments, claim fingerprints and ended benefits removed. It removes claims 30 days after the first terminal time while keeping the completed count. It removes account-bound benefit, acceptance and replay detail 90 days after the end. Both remain independent: a terminal code's fingerprints may be removed while its already granted benefit continues.

### Support-requested account deletion

Use the privileged owning command after verifying the deletion request under the Instance's support process:

```sh
docker compose exec backend python -m pumpkit.account_deletion --user-id user_ID
```

The command first locks the User, then its Scheduled post rows in identifier order, then affected Coupons. It refuses deletion while any post is publishing, so an X call already in flight can settle and retain its returned X identifier. Wait for publishing or recovery to finish before retrying; do not delete those rows manually. Locking waiting Scheduled posts also prevents the publisher from claiming one between the check and account deletion. It refuses unresolved Subscriptions, paid Checkouts or invoice/payment obligations; a saved card alone is not an obligation. Resolve actual billing obligations before retrying. It does not cancel a Subscription. It deletes the profile, sign-in links for its normalized email, Sessions, content and account-bound benefit/acceptance/results through their owning services and database cascades. Only protected claims without the old account identifier and nonpersonal completed counts survive as specified above. Recreating the same email therefore cannot claim the same still-redeemable Coupon again.

Stored Media files need a separate retryable cleanup after the database commit. The deletion transaction queues their storage keys without retaining a profile or email. File cleanup removes each queued key and then its queue record. On failure the command returns nonzero; retry it or run `python -m pumpkit.account_deletion --retry-files` with the same protected configuration. Run `--retry-files` daily alongside Coupon purge, inspect failure status and retry immediately. Do not declare content deletion complete while queued files remain. Both commands work with Coupons disabled.

**Upgrade notes:** Apply migration 0045 before deploying this slice. Add the daily `--retry-files` command to the existing purge job and use the owning deletion command instead of directly deleting User rows. Keep the complete identity key ring. The feature remains disabled outside isolated tests pending final #394.

### PostgreSQL contention checks

The ordinary suite still uses SQLite and needs no service. To exercise production row locks, explicitly supply a PostgreSQL URL to `PUMPKIT_TEST_POSTGRES_URL` and run `uv run --extra dev pytest tests/billing/postgres -q` from `backend/`. The harness creates a random isolated schema per test, sets every connection's search path and drops only that schema. It never drops or rewrites the supplied database's public schema. Independent authenticated HTTP requests contend on held rows for last-slot, same-identity, same-operation, disable, deletion and waiting-deadline cases, plus Top-up creation/deletion ordering across first-customer commits.


### Appending free months in Settings

With Coupons enabled, the Plan card in Settings offers **Redeem coupon**, using the same preview and two-box confirmation as the Paywall. A distinct Coupon appends after remaining Free access. Preview shows the new grant's dates; the Plan card shows the combined end prominently plus the current grant and queued ranges, and Usage retains the current period, usage and Top-ups. After success those reads and access state refresh. Another browser reads the same committed coverage on reload. No Subscription or automatic payment is created.

Each grant retains its own claim, acceptance, operation result and accepted monthly caps. Current-period caps and usage remain unchanged when a new offer has different caps; those caps apply only in its queued months. The grant persists the original UTC calendar anchor and its whole-month offset, so January 31 clips to February's last day and then returns to March 31. Purging an earlier ended grant never changes a queued grant's anchor. Purge still removes each grant's detail 90 days after its own end.

The signed preview binds the preceding grant and offset as well as the offer. Confirmation serializes on the User lock, so a competing append changes the offer and requires a new preview and acceptance. It never silently shifts the grant or consumes a stale claim. The combined end, including all remaining free time, must be at most 730 × 86400 seconds after confirmation; an unsupported offer is refused without consuming it. Deadlines govern confirmation only, and disabling a code preserves already queued months.

**Upgrade notes:** Apply migration 0046 before deploying this slice. It preserves existing grant anchors and adds offsets for subsequent appends. Keep the shared setting off outside isolated tests pending final #394. Subscriber deferral, buying Top-ups during Free access and paid signup that preserves free months remain separate implementation slices.

### Top-ups during free access

While free access is current, Usage offers the normal Buy top-up action, including for a recipient with no subscription or a provider subscription reported as trialing after deferral. The one-time purchase uses the existing pack, price and paid Terms confirmation; it creates no recurring subscription and preserves the full free period. Operators need no additional setting or product.

The full monthly allowance is spent first, then unexpired previously purchased packs, earliest expiry first. Packs retain their existing 12-month expiry and refund/dispute removal rules. Queued free months alone do not qualify a current introductory trial or overdue payment for purchase: their existing Subscribe now or payment action remains. Instances without Plans or a configured top-up price offer no purchase. Already granted access and its top-ups continue when coupon issuance/redemption is disabled.

Support account deletion refuses while any Checkout is open or a completed one-time payment is unresolved, including asynchronous payments without an invoice. It does not expire or cancel payments automatically. Resolve an open Checkout by completing or explicitly expiring it through the provider; for a completed asynchronous payment, wait for settlement or obtain a confirmed canceled PaymentIntent through the provider where cancellation is supported. Paid, no-payment-required, expired and confirmed canceled one-time payment history does not block deletion. Missing or unknown provider facts require investigation before deletion. Top-up creation and deletion share the User lock, including after first-customer creation commits.
