import { errorMessage, errorStatus } from '@/services/apiErrors';

/** The `detail` of billing's `require_subscribed_user` refusal, as the backend words it. */
const SUBSCRIPTION_NEEDED = 'This needs a subscription. Subscribe to continue.';

/** Whether a request was refused for want of a Subscription, not some other 403. */
export function isSubscriptionNeeded(e: unknown): boolean {
  return errorStatus(e) === 403 && errorMessage(e, '') === SUBSCRIPTION_NEEDED;
}
