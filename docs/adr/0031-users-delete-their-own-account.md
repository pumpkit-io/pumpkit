---
status: accepted
---

# Users delete their own account, which ends a Running Subscription at once

Until now a User deleted their account by writing to support, and the Operator ran `python -m pumpkit.account_deletion` within 30 days. That command refuses while a Subscription hasn't ended, so the Operator had to wait for or arrange its end. A User now deletes their account themselves in Settings, and it takes effect at once. Writing to support stays for a User who can't sign in.

- Deletion cancels a Running Subscription in Stripe immediately, with no refund, and expires any open checkout, as the Terms already promised. Refusing instead would make a User on a Trial cancel renewal and wait out the period before they could leave. When Stripe refuses the cancel, nothing is deleted and the User is asked to try again or contact support.
- Deletion still refuses while a Scheduled post is being published, while a plan change, paid signup or Coupon redemption is pending, and while an invoice is unpaid. Each refusal tells the User what to do: wait, or contact support for an unpaid invoice.
- Deletion disconnects X: after the deletion commits, Pumpkit revokes its X token. A failed revoke is logged and doesn't undo the deletion, since the tokens are gone from Pumpkit either way. X may revoke the grant for the whole X account, which deletion wants.
- What deletion keeps is unchanged: the Trial eligibility and Coupon claim fingerprints, and Stripe's billing records. Signing in again with the same X account makes a new User with no new Trial.
- Only the web app deletes an account. No MCP tool does, so no Connected app can.
