import { useState } from 'react';
import { ErrorBanner } from '@/components/ErrorBanner';
import { SettingsCard } from '@/components/SettingsCard';
import { Badge, type BadgeProps } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { track } from '@/lib/analytics';
import { redirectTo } from '@/lib/navigation';
import { cn } from '@/lib/utils';
import { errorMessage } from '@/services/apiErrors';
import {
  billingService,
  type Subscription,
  type SubscriptionStatus,
} from '@/services/billingService';
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

function statusBadgeVariant(status: SubscriptionStatus): BadgeProps['variant'] {
  if (status === 'active') return 'success';
  if (status === 'trialing') return 'accent';
  return PAYMENT_FAILED_STATUSES.has(status) ? 'warning' : 'default';
}

// A Trial's period end is its first charge, unless the User cancelled before it.
function nextBillingLabel({ status, cancelAtPeriodEnd }: Subscription): string {
  if (cancelAtPeriodEnd) return 'Ends on';
  return status === 'trialing' ? 'Billing starts on' : 'Renews on';
}

/** The User's Plan, its status and next billing date, with the billing portal for the rest. */
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

  const subscription = data?.me.subscription ?? null;
  const plan = subscription ? data?.plans.find((p) => p.key === subscription.planKey) : undefined;
  const paymentFailed = subscription ? PAYMENT_FAILED_STATUSES.has(subscription.status) : false;

  return (
    <SettingsCard title="Plan">
      {loadError && <ErrorBanner message={loadError} />}
      {error && <ErrorBanner message={error} />}
      {!data ? (
        isLoading && (
          <p role="status" className="font-sans text-sm text-muted-foreground">
            Loading your plan…
          </p>
        )
      ) : subscription ? (
        <div className="overflow-hidden rounded-lg border border-border">
          {paymentFailed && (
            <p className="border-b border-warning/30 bg-warning/10 px-4 py-2.5 font-sans text-sm text-warning">
              Your last payment failed. Update your card to keep access.
            </p>
          )}
          <div className="flex items-center justify-between gap-3 px-4 py-4">
            <div className="min-w-0">
              <p className="truncate font-sans text-lg font-semibold leading-tight text-foreground">
                {plan?.productName ?? 'Your plan'}
              </p>
            </div>
            <Badge variant={statusBadgeVariant(subscription.status)} className="shrink-0">
              {STATUS_LABELS[subscription.status]}
            </Badge>
          </div>
          <div className="flex flex-col gap-3 border-t border-border bg-muted/40 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
            {/* While a payment fails Stripe retries it, so nothing renews on the period end. */}
            {subscription.currentPeriodEnd && !paymentFailed && (
              <p className="font-sans text-sm text-foreground">
                {`${nextBillingLabel(subscription)} ${new Date(
                  subscription.currentPeriodEnd,
                ).toLocaleDateString(undefined, { dateStyle: 'long' })}`}
              </p>
            )}
            <Button
              type="button"
              variant={paymentFailed ? 'default' : 'outline'}
              className={cn('h-10 shrink-0 sm:ml-auto', !paymentFailed && 'bg-card')}
              onClick={() => void openPortal()}
            >
              {paymentFailed ? 'Fix payment' : 'Manage subscription'}
            </Button>
          </div>
        </div>
      ) : null}
    </SettingsCard>
  );
}
