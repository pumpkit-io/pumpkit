import { useState } from 'react';
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import {
  billingService,
  errorMessage,
  type Subscription,
  type SubscriptionStatus,
} from '@/services/billingService';
import { redirectTo } from '@/lib/navigation';
import { track } from '@/lib/analytics';
import { useBilling } from './useBilling';
import { PlanCard, recurringLabel } from './PlanCard';

function ErrorBanner({ message }: { message: string }) {
  return (
    <div
      role="alert"
      aria-live="polite"
      className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 font-sans text-xs text-red-700 dark:text-red-300"
    >
      {message}
    </div>
  );
}

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

function RunningSubscription({
  subscription,
  onManage,
}: {
  subscription: Subscription;
  onManage: () => void;
}) {
  const paymentFailed = PAYMENT_FAILED_STATUSES.has(subscription.status);
  return (
    <div className="space-y-3 rounded-xl border border-border bg-card p-4">
      {paymentFailed && (
        <div
          role="alert"
          className="rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 font-sans text-xs text-amber-700 dark:text-amber-300"
        >
          Your last payment failed. Update your card to keep access.
        </div>
      )}
      <div className="flex items-center justify-between gap-3">
        <div className="font-sans text-sm text-foreground">
          Status: <span className="font-medium">{STATUS_LABELS[subscription.status]}</span>
          {subscription.currentPeriodEnd && (
            <span className="text-muted-foreground">
              {' '}
              · {subscription.cancelAtPeriodEnd ? 'ends' : 'renews'}{' '}
              {new Date(subscription.currentPeriodEnd).toLocaleDateString()}
            </span>
          )}
        </div>
        <Button type="button" variant="outline" size="sm" onClick={onManage}>
          {paymentFailed ? 'Fix payment' : 'Manage subscription'}
        </Button>
      </div>
    </div>
  );
}

export function BillingDialog() {
  const { isOpen, close, error, openWithError, data, isLoading } = useBilling();
  const [pendingId, setPendingId] = useState<string | null>(null);

  const go = async (id: string, start: () => Promise<string>) => {
    setPendingId(id);
    try {
      redirectTo(await start());
    } catch (e) {
      const message = errorMessage(e, 'Could not start checkout. Please try again.');
      track('billing_checkout_redirect_failed', { error_message: message });
      openWithError(message);
      setPendingId(null);
    }
  };

  const onSubscribe = (planKey: string) => {
    track('billing_subscription_checkout_started', { plan_key: planKey });
    void go(planKey, () => billingService.startSubscriptionCheckout(planKey));
  };

  const onManage = async () => {
    try {
      const url = await billingService.openBillingPortal();
      track('billing_portal_opened');
      redirectTo(url);
    } catch (e) {
      openWithError(errorMessage(e, 'Could not open the billing portal.'));
    }
  };

  const subscription = data?.me.subscription;

  return (
    <Dialog open={isOpen} onOpenChange={(next) => (next ? null : close())}>
      <DialogContent className="max-w-[640px]">
        <DialogHeader>
          <DialogTitle className="font-sans text-base font-semibold tracking-tight">
            Billing
          </DialogTitle>
          <p className="mt-1 font-sans text-xs text-muted-foreground">Manage your Subscription.</p>
        </DialogHeader>

        <div className="max-h-[65vh] space-y-6 overflow-y-auto px-6 pb-4">
          {error && <ErrorBanner message={error} />}
          {isLoading && !data && (
            <div role="status" className="py-6 font-sans text-sm text-muted-foreground">
              Loading…
            </div>
          )}

          {data && (
            <>
              <section className="space-y-3">
                <h3 className="font-sans text-sm font-semibold text-foreground">Subscription</h3>
                {data.me.maySubscribe ? (
                  <>
                    <p className="font-sans text-xs text-muted-foreground">
                      Choose a Plan to subscribe.
                    </p>
                    {data.plans.length === 0 ? (
                      <p className="font-sans text-xs text-muted-foreground">
                        No Plans are available yet.
                      </p>
                    ) : (
                      <div className="grid gap-3 sm:grid-cols-2">
                        {data.plans.map((plan) => (
                          <PlanCard
                            key={plan.key}
                            title={plan.productName}
                            priceLabel={recurringLabel(
                              plan.amount,
                              plan.currency,
                              plan.interval,
                              plan.intervalCount,
                            )}
                            note={
                              data.me.trialDays === null
                                ? undefined
                                : `${data.me.trialDays}-day free Trial`
                            }
                            actionLabel={pendingId === plan.key ? 'Redirecting…' : 'Subscribe'}
                            ariaLabel={`Subscribe to ${plan.productName}`}
                            disabled={pendingId !== null}
                            onAction={() => onSubscribe(plan.key)}
                          />
                        ))}
                      </div>
                    )}
                  </>
                ) : (
                  subscription && (
                    <RunningSubscription subscription={subscription} onManage={onManage} />
                  )
                )}
              </section>
            </>
          )}
        </div>

        <DialogFooter>
          <button
            type="button"
            onClick={onManage}
            className="font-sans text-xs text-muted-foreground underline-offset-2 hover:underline"
          >
            Payments &amp; invoices →
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
