# Prelaunch X-only cutover

This procedure is for the operator's explicitly authorized test accounts in #446. It is separate from normal deletion and never runs during startup or migration. Production rollout is incomplete until its results are observed.

## Prerequisites

1. Merge the complete reviewed stack, then use [the release procedure](releasing.md). The private operations repository's `deploy.md` installs only published full releases. Never deploy a feature-branch image or reset production while that prerequisite is unmet.
2. Check the real configured X app: every `X_SIGN_IN_SCOPES` permission including `users.email`, confirmed-email entitlement, exact registered `PUBLIC_URL/oauth/x/callback`, profile, refresh and publishing/media permissions. The local stand-in proves none of these entitlements. Missing confirmed email blocks rollout, without enabling another sign-in method.
3. Configure X credentials, valid Fernet encryption and the persistent trial ring. Preserve complete trial and coupon rings, including historical keys, with the database. Follow [key custody](self-hosting.md#x-account-trial-eligibility); never regenerate a ring or replace bytes under an existing key ID.
4. Use private operations `scripts/backup.sh` and `deploy.md`. Verify a nonempty database dump and protected configuration backup, including both complete rings. Record only nonsecret paths/status. That backup is not a media-file backup; take a protected storage backup if deliberately removed files must be recoverable.
5. Install the complete published release through the supported deployment script, completing applicable Upgrade notes before passing `--upgrade-notes-done`. The reset CLI below is available only after its supplying release is installed. Reset is a separate maintenance operation before the selected test accounts resume use.

## Inspect and select

Inspect current user IDs, contact/X identity and Stripe customer association in a protected operator session. Keep personal data and provider identifiers in a protected record, not issues or shell transcripts. Previous permission covers the operator's three test accounts; verify current count and ownership. Write an explicit selected-ID list. Never execute against all current users, an email wildcard or a truncated table.

For each selected account inspect subscriptions, pending/completed-but-unsettled checkout/payment/setup intents, invoices, pending coupon/paid-signup/frequency work, publishing claims, posts/media/files, sessions and connected-app grants. Use [billing recovery](coupons.md#support-requested-account-deletion) and provider status. Resolve/cancel actual obligations through supported provider dashboard/portal and recovery interfaces, then wait for reconciliation. Never delete pending rows or force a payment/publication result. A saved card alone is not an obligation.

Quiesce the selected accounts' browser/MCP clients during maintenance. Stop initiating X authorization, wait at least the ten-minute pending sign-in lifetime after the last attempt, discard old callbacks/consent attempts, and restart afterwards. A pending sign-in has no user yet, so selected-user deletion cannot identify or revoke it. Do not broadly purge another browser's attempts or global client registrations. The CLI does not prevent a fresh sign-in; if this maintenance boundary cannot be established, stop the actual reset.

## Preview and execute

From the deployed instance directory with protected configuration, replace `user_ID` with one inspected, explicitly selected ID:

```sh
docker compose exec -T backend python -m pumpkit.account_deletion --user-id user_ID --prelaunch-reset
```

For non-compose installations, run the module in the installed backend with the same protected settings. In development, reach only the selected worktree's backend through its dev-stack contract.

The prelaunch mode previews by default. It uses the existing billing, pending-operation and publishing guards, reads provider status where needed, and rolls back local synchronization. It does not cancel, expire, charge, revoke or delete provider resources, account data, fingerprints or files. JSON prints counts only: `executed`, `users`, `coupon_claims`, `trial_eligibility` and `files`.

- Trial records match the selected user's stored stable X ID across historical keys.
- Claims match that X ID, a current legacy-email identity or a direct benefit/operation reference. A different X fingerprint is preserved; a claim referenced by another account refuses reset.
- An unlinked email-only claim cannot be attributed to a current X identity, even without another live account sharing its email. It also refuses for a legacy account with another live account sharing that email. Missing historical keys refuse too. Investigate attribution or restore keys; never purge all retained claims.
- An old unlinked claim under an earlier email that cannot be attributed remains. Already-deleted accounts with no current user record cannot be reset; do not guess identity from a fingerprint.
- Issuance, recipient assignments, counters, capacity, deadlines and terminal/disabled status remain. Clearing a test claim neither reopens an exhausted coupon nor grants access.

After preview and all provider/backup prerequisites succeed, explicitly execute the same selected ID:

```sh
docker compose exec -T backend python -m pumpkit.account_deletion --user-id user_ID --prelaunch-reset --execute
```

Execution repeats guards under the user lock, locks affected coupons in identifier order, and commits selected account/fingerprint removal together through the existing deletion owner. Profile/credentials, sessions/refresh tokens, connected-app grants/tokens, posts/versions/media references, waiting scheduled work and account-bound billing/acceptance/replay rows follow existing foreign-key cascades. Global client registrations, unrelated accounts/fingerprints, issuance/configuration and provider resources remain.

Selected media keys are queued transactionally. After commit only those files and queue entries are removed; unrelated pending file cleanup remains. A file error returns nonzero after the database commit. Retry through the existing owner, which intentionally processes the already-authorized global cleanup queue:

```sh
docker compose exec -T backend python -m pumpkit.account_deletion --retry-files
```

Do not repeat reset after the user is gone: identity attribution is unavailable and the command refuses. Do not declare content deletion complete while selected files remain. Publish aggregate counts/status only; privately verify selected rows/files are gone and unrelated state is unchanged. Stripe customer/invoice/payment records keep their provider retention. The CLI does not claim remote X authorization revocation.

Normal `python -m pumpkit.account_deletion --user-id user_ID` intentionally preserves trial eligibility and coupon claims. Never use the prelaunch exception for ordinary deletion or support-requested benefit restoration.

## Postchecks and stops

Observe the selected real accounts: first/returning sign-in, confirmed contact, read-only identity/X photo, retained name, Paywall then Persona, same-account recovery, authorization/refresh and media permissions. Prove legacy sign-in cannot authenticate with old credentials configured. Verify connected-app consent and session refresh. Use normal deletion/recreation, without the reset flag, to prove benefit restrictions persist afterwards. Keep coupons disabled pending #394, #429 and #430.

Follow release smoke checks and the private operations deployment/rollback checks. Restore only compatible database/configuration backups with matching complete rings. A database-only restore cannot recover deliberately deleted files.

Record observed release SHA/version, backup success/path, aggregate inspected/reset counts and real-provider outcomes on #446. Leave rollout incomplete for an unmerged stack, unverified real-X entitlement/callback, uncertain payment, active publication, missing key, ambiguous claim, failed cleanup or any unobserved production result. None is inferred success.
