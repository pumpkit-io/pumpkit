# Coupon implementation and operations contract

This is the implementation contract for spec #392, settled by #396. Coupons remain unavailable until the later tickets implement these rules. The public English and Italian documents describe the complete feature; publishing them does not activate it or constitute legal approval. Self-hosters supply their own legal documents.

## Activation and provider evidence

#395 introduces `COUPONS_ENABLED=false`, the one default-off feature setting. Off means no issuance, preview, redemption or coupon-specific paid signup/Plan-change actions and no coupon affordances. Ordinary billing and Instances that sell no Plans keep their existing behavior. Coupon functionality also requires configured Plans. Enable it only in isolated test environments until final #394 passes.

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

| Record | Retain until | Purge behavior and owner |
|---|---|---|
| Unclaimed recipient assignment | Permanently unclaimable and all related operations resolved | Remove fingerprint/key identifier within 30 days; #395. No-deadline codes retain their assignment while claimable. |
| Claim fingerprint, including after account deletion | Same terminal condition | Remove within 30 days; #398. Keep a nonpersonal completed-claim count so purging cannot restore capacity. |
| Active/queued benefit and its acceptance | Benefit end and resolution of related operations | Remove within 90 days of the later event; #398. Account deletion ends benefits and removes the account link immediately, retaining only required claim/recovery evidence. |
| Pending recovery intent/evidence | Confirmed reconciliation or definite refusal | Never age out unresolved work; #401. Keep only stable operation/provider identifiers, accepted offer, target and original coverage facts needed for recovery. |
| Resolved recovery/audit evidence | Resolution and end of related benefits | Remove within 90 days of the later event; #401. Do not keep raw provider payloads or recipient email. |
| Backups containing removed data or old keys | Last live removal | Existing rotation removes copies within 30 days. Reapply purge after restore before serving traffic. |

Where one row serves several purposes, remove unnecessary fields independently and retain only fields whose purpose remains. Account deletion detaches the User but preserves claim fingerprints and the minimum unresolved billing evidence. It must serialize with redemption/recovery and must not allow later recovery to grant orphaned access or charge a deleted account. A pending operation keeps enough deletion intent to finish safely; it does not retain the deleted profile or content. A legal hold must be separately justified, documented and limited to its actual records, not silently applied to every Coupon.

#395 supplies privileged `uv run python -m pumpkit.billing.coupons purge` from `backend/`; #398 and #401 extend that command for their records. Run it daily with the same Instance configuration and database privileges, including when `COUPONS_ENABLED=false`. It must be idempotent and safe against concurrent claims, disable and recovery, with the same lock order as redemption. Inspect its nonsecret counts and failures; retry a failed daily run immediately. Check unresolved operations daily, flag anything pending more than 24 hours and investigate until resolved; there is no destructive age-based timeout. #401 supplies the independent recovery invocation and its lock order. Do not log keys, codes, email assignments, fingerprints or full provider responses in purge/recovery output.

## Upgrading and self-hosting

This contract does not introduce runtime keys or a runnable Coupon command by itself. #395 introduces their configuration, migration and executable purge command together; do not enable Coupons until those and later implementation slices are installed and #394 is complete. At that point, install a daily purge/recovery job, back up the complete key ring securely with the database recovery process, replace the legal documents for your Instance and verify the disabled setting before starting it. Each runtime ticket adds its applicable Upgrade notes. An Instance selling no Plans needs no Coupon key or job.

Publishing these changed legal documents does not send the material-change notice promised in clause 19. The Operator must arrange that notice before applying a material change to existing Users; this PR sends no email. Self-hosters follow their own notice obligations and bump the frontend/backend Terms dates together when replacing the documents.
