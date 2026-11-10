# X is the only sign-in method

Pumpkit uses X as its only sign-in method: the X account a User signs in with is also the account they publish through. This removes the separate X connection step from Onboarding and the ability to replace the X account in Settings, and prevents obtaining another Trial merely by signing up with another email address.

Keep the Google and Magic link flow implementations in the codebase, but disable them in both the backend and frontend. There is no supported configuration switch to enable them; someone who wants them must change the code. Their presence must not imply that they are usable sign-in methods. This applies to every Instance, including Self-hosters' Instances.

The Operator has confirmed that the three existing production Users belong to them and that local and production user data may be deleted. Plan a clean reset instead of an account migration flow. This permission does not require executing a reset during this design interview.

This decision supersedes ADR 0002's Google/Magic link restriction, ADR 0006's separation of X authorization from sign-in, ADR 0011's sign-in fallbacks, and ADR 0018's separate X connection onboarding step. Other decisions in those ADRs continue to apply.

## Identity and email

Identify a User by X's stable user ID, never by handle or email. Request the `users.email` permission and require a confirmed email from X before completing sign-in. Email is contact information rather than account identity. Distinct X accounts may share an email address and remain separate Users. Update the contact email from X on every successful sign-in; never merge Users because their emails match. When X supplies no confirmed email, explain that the User must add one on X and retry; do not introduce another email-verification flow.

## Trial eligibility

Each X account gets at most one Trial per Instance, including after account deletion and recreation. Keep a minimal eligibility record across deletion so changing email or handle does not restore eligibility. Distinct X accounts can qualify separately. Receiving Coupon benefits also permanently removes that X account’s Trial eligibility.

## Publishing authorization

Request sign-in and all required publishing permissions together. Every successful sign-in restores publishing authorization. An already signed-in User can restore revoked or expired authorization through a Reconnect X prompt that only accepts their original X user ID. Remove the Settings controls for switching or disconnecting the X account.

## Coupons

Keep email-restricted Coupon recipients, matched against the confirmed email supplied by X. Prevent repeat redemption of the same Coupon by either the same X account or the same verified email, including after deletion and recreation. This extends ADR 0022's verified-email restriction with an X-account restriction.

## Sessions and reconnection

Losing publishing authorization does not end the Pumpkit Session. Writing, billing and account deletion remain available under their usual access rules; publishing is blocked until authorization is restored. A reconnection with a different X user ID is rejected with guidance to use the original account. Signing out and signing in with a different X account opens that account's separate Pumpkit account.

## Profile

Keep name editing. Initially use X's display name; preserve later Pumpkit name edits. Show the X handle and confirmed email as read-only account information in the Profile card. Remove the separate X account card.

Always use X's photo and remove Pumpkit photo editing, uploading, removal and source-selection controls. Update the stored photo when an existing X profile fetch returns a changed photo. Do not add polling, background synchronization or an extra X request solely to update a photo. An ordinary Pumpkit profile read must not acquire a new X request just for photo synchronization.

## UI design plan

Retain the current UI direction rather than introducing a new visual identity. Reuse existing light and dark theme tokens, the mascot and motion preferences, Inter body text, Bricolage Grotesque display text where already used, spacing and components. The existing brand references are Pumpkin `#D96B45`, Charcoal `#20201E`, Ivory `#F7F5EF` and Olive `#66734E`; use the existing semantic tokens for actual surfaces, text and controls.

Login keeps the existing two-column desktop layout with the mascot aside; narrow screens keep the single content column. Content remains left aligned inside the centered login card. Replace the Google button, divider and email form with one full-width Continue with X button and a plain sentence explaining that continuing also authorizes publishing. Keep the existing legal links and footer.

```text
Desktop login
[ Welcome + explanation + Continue with X ] [ Existing mascot aside ]

Narrow login
[ Welcome                                      ]
[ Explanation                                 ]
[ Continue with X                             ]
[ Legal links                                 ]

Settings
[ Profile: X photo, editable names, @handle, email ]
[ Existing billing and connected-app cards        ]
```

After sign-in, preserve the Paywall where applicable, then show Persona setup directly. Remove the X connection step and its success interstitial. Existing Persona loading, empty and error states remain relevant. Remove the separate X Settings card and photo-offer dialogs. No new dashboard or redesign is needed.

While opening X, disable the login button and show Opening X…. The callback shows a signing-in status. Cancellation, expired authorization, provider failure and missing confirmed email return actionable errors with a retry path; a missing email message directs the User to confirm an email on X. Preserve intended in-app destinations through sign-in, including Connected app consent, subject to the existing access gates.

The existing reconnect banner explains that scheduled posts cannot go out and offers Reconnect X. Show progress while opening X and an actionable error if it fails. Reject a mismatched account without changing identity or saved publishing credentials. Profile loading retains a status message; an unavailable X photo uses the existing initials fallback, without an upload or removal action.

Review against the brief: the plan removes unnecessary sign-in and connection choices, makes the publishing permission explicit, and preserves Pumpkit's existing identity. It sets no new design direction and needs no new fonts, palette or decorative elements.

## Eligibility retention

Keep a minimal Trial eligibility record for the lifetime of the Instance: a keyed fingerprint of the stable X ID and whether a Trial or Coupon benefit has removed eligibility. After User deletion, this eligibility record contains no email, handle, photo, Posts or publishing tokens. Key management must preserve matching across key rotation so rotation cannot restore eligibility. Describe this retention in the Privacy Policy. Coupon-specific claim records remain subject to their own retention contract.

## Sign-up restrictions and configuration

Keep the email/domain Sign-up allowlist and check X's confirmed email on every sign-in. An empty list allows everyone. A changed X email outside the allowlist causes the next sign-in to be refused.

The backend refuses to start with a clear configuration error when required X sign-in settings are missing. Google credentials and SMTP settings never activate another sign-in method. Every Instance now requires X sign-in configuration; setup and Self-hosting instructions must make that requirement clear.

## Inputs to the specification

- Implement unauthenticated, browser-bound X sign-in and same-account reconnection, with the existing OAuth safeguards, stable X identity, email requirements, backend gates and Session behavior above. Adapt API and MCP tools so they cannot replace or disconnect that identity.
- Preserve Google and Magic link implementations as inactive code, without a supported enablement switch. Make the active X-only policy explicit in agent guidance and auth documentation so retained flows are not mistaken for usable entry points.
- Implement durable Trial and Coupon eligibility under shared and changing emails, User deletion and concurrent requests, including key rotation and retained identity matching.
- Implement the UI plan, removing profile-photo editing and the separate X connection step/card while preserving name edits and updating X photos only through existing profile-fetch opportunities.
- Prepare and execute the authorized clean reset in local and production environments through their supported operations procedures, handling dependent user data, Media, Sessions, Connected app grants and billing-provider resources as needed. Inspect provider state before resetting local records; no general account migration flow is required.
- Update configuration, setup, Self-hosting, development, auth, MCP and Coupon documentation and agent rules affected by the decision. Update the Privacy Policy and review related legal copy for the changed sign-in and retention behavior. Supply Upgrade notes and the User/Self-hoster changelog entry for the implementation PR.
- Verify disabled entry points, sign-in/reconnection and error states, account isolation, eligibility across deletion, onboarding, photo behavior and provider configuration. Open the implementation PR and run the repository's required checks and admin-triggered review.

No feature code, data reset, spec, tickets or issues are produced by this interview. The UI plan retains the existing design direction, so it does not require an update-design run.
