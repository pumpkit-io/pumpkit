import { useState } from 'react';
import { ErrorBanner } from '@/components/ErrorBanner';
import { SettingsCard } from '@/components/SettingsCard';
import { Button } from '@/components/ui/button';
import { track } from '@/lib/analytics';
import { redirectTo } from '@/lib/navigation';
import { errorMessage } from '@/services/apiErrors';
import { billingService, type SubscriptionStatus } from '@/services/billingService';
import type { BillingData } from './BillingProvider';

// How each Subscription status reads to the User. Ended ones are never shown.
const STATUS_LABELS: Record<SubscriptionStatus, string> = {
  trialing: 'Trial',
  active: 'Active',
  past_due: 'Past due',
  unpaid: 'Unpaid',
  paused: 'Paused',
  incomplete: 'Incomplete',
  incomplete_expired: 'Ended',
  canceled: 'Ended',
};

// A Running Subscription in one of these is behind on payment, or stopped over it.
const PAYMENT_FAILED_STATUSES: ReadonlySet<SubscriptionStatus> = new Set([
  'past_due',
  'unpaid',
  'paused',
]);

/** The User's Plan, its status and renewal date, with the billing portal for the rest. */
export function SubscriptionCard({
  data,
  isLoading,
  loadError,
}: {
  data: BillingData | null;
  isLoading: boolean;
  loadError: string | null;
}) {
  const [error, setError] = useState<string | null>(null);

  const openPortal = async () => {
    setError(null);
    try {
      const url = await billingService.openBillingPortal();
      track('billing_portal_opened');
      redirectTo(url);
    } catch (e) {
      setError(errorMessage(e, "Couldn't open the billing portal. Try again."));
    }
  };

  // An `incomplete` Subscription is a checkout still open: the User may subscribe again.
  const subscription = data && !data.me.maySubscribe ? data.me.subscription : null;
  const planName = subscription
    ? (data?.plans.find((plan) => plan.key === subscription.planKey)?.productName ?? null)
    : null;
  const paymentFailed = subscription ? PAYMENT_FAILED_STATUSES.has(subscription.status) : false;

  return (
    <SettingsCard title="Plan">
      {loadError && <ErrorBanner message={loadError} />}
      {error && <ErrorBanner message={error} />}
      {!data ? (
        isLoading && (
          <p role="status" className="font-sans text-sm text-muted-foreground">
            Loading your Plan…
          </p>
        )
      ) : subscription ? (
        <div className="space-y-3">
          {paymentFailed && (
            <p className="rounded-md border border-warning/40 bg-warning/10 px-3 py-2 font-sans text-xs text-warning">
              Your last payment failed. Update your card to keep access.
            </p>
          )}
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="min-w-0 space-y-0.5">
              {planName && (
                <p className="font-sans text-sm font-semibold text-foreground">{planName}</p>
              )}
              <p className="font-sans text-sm text-muted-foreground">
                <span className="font-medium text-foreground">
                  {STATUS_LABELS[subscription.status]}
                </span>
                {subscription.currentPeriodEnd && (
                  <>
                    {' '}
                    · {subscription.cancelAtPeriodEnd ? 'ends' : 'renews'}{' '}
                    {new Date(subscription.currentPeriodEnd).toLocaleDateString()}
                  </>
                )}
              </p>
            </div>
            <Button
              type="button"
              variant="outline"
              className="h-10 shrink-0"
              onClick={() => void openPortal()}
            >
              {paymentFailed ? 'Fix payment' : 'Manage subscription'}
            </Button>
          </div>
        </div>
      ) : (
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="space-y-0.5">
            <p className="font-sans text-sm font-semibold text-foreground">No Subscription</p>
            <p className="font-sans text-sm text-muted-foreground">
              Choose a Plan above to start writing.
            </p>
          </div>
          <button
            type="button"
            onClick={() => void openPortal()}
            className="self-start font-sans text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline sm:self-auto"
          >
            Past payments and invoices
          </button>
        </div>
      )}
    </SettingsCard>
  );
}
