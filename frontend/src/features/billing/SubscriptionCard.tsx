import { useEffect, useRef, useState } from 'react';
import { CouponForm } from './CouponForm';
import { PaidSignup } from './PaidSignup';
import { PlanChange, FuturePlanDetails } from './PlanChange';
import { ErrorBanner } from '@/components/ErrorBanner';
import { SettingsCard } from '@/components/SettingsCard';
import { Badge, type BadgeProps } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import {
  billingService,
  type Subscription,
  type SubscriptionStatus,
} from '@/services/billingService';
import { errorMessage } from '@/services/apiErrors';
import { useBilling } from './useBilling';
import type { BillingData } from './BillingProvider';
import { useOpenPortal } from './useOpenPortal';

function freeDate(value: string): string {
  return `${new Date(value).toLocaleDateString(undefined, { dateStyle: 'long', timeZone: 'UTC' })} UTC`;
}

// Ended provider subscriptions can still carry earned local paid coverage.
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

// A Trial's period end is its first charge; a cancelled Subscription only has its end.
function nextDateLabel({ status, currentPeriodEnd, cancelAt }: Subscription): string | null {
  const [label, date] = cancelAt
    ? ['Ends on', cancelAt]
    : [status === 'trialing' ? 'Billing starts on' : 'Renews on', currentPeriodEnd];
  if (!date) return null;
  return `${label} ${new Date(date).toLocaleDateString(undefined, { dateStyle: 'long' })}`;
}

/** The User's Plan, its status and next billing date, with the billing portal for the rest. */
export function SubscriptionCard({
  data,
  isLoading,
  loadError,
  onRedeemed,
}: {
  data: BillingData | null;
  isLoading: boolean;
  loadError: string | null;
  onRedeemed?: () => void;
}) {
  const { openPortal, error } = useOpenPortal();
  const { load } = useBilling();
  const [canceling, setCanceling] = useState(false);
  const [localPending, setLocalPending] = useState(false);
  const [signupPending, setSignupPending] = useState(false);
  const [changePending, setChangePending] = useState(false);
  const [cancelError, setCancelError] = useState<string | null>(null);
  const [canceledThrough, setCanceledThrough] = useState<string | null>(null);
  const cancellation = useRef<HTMLParagraphElement>(null);
  useEffect(() => {
    if (canceledThrough) cancellation.current?.focus();
  }, [canceledThrough]);
  async function cancelRenewal() {
    setCanceling(true);
    setCancelError(null);
    try {
      const answer = await billingService.cancelRenewal();
      setCanceledThrough(answer.subscription?.cancelAt ?? null);
      await load();
    } catch (cause) {
      setCancelError(errorMessage(cause, "Couldn't confirm cancellation. Try again to check."));
    } finally {
      setCanceling(false);
    }
  }

  const subscription = data?.me.subscription ?? null;
  const freeAccess = data?.me.freeAccess;
  const plan = subscription ? data?.plans.find((p) => p.key === subscription.planKey) : undefined;
  const paymentFailed = subscription ? PAYMENT_FAILED_STATUSES.has(subscription.status) : false;
  const deferral = data?.me.couponDeferral;
  const pending = data?.me.pendingCouponOperation || localPending;
  const planChangePending = changePending || Boolean(data?.me.pendingPlanChangeId);
  const billingBlocked =
    pending || signupPending || Boolean(data?.me.pendingPaidSignupId) || planChangePending;
  const renewalCancelled = Boolean(
    subscription?.cancelAt ||
    subscription?.status === 'canceled' ||
    subscription?.status === 'incomplete_expired',
  );
  const next =
    subscription && !billingBlocked
      ? deferral && !renewalCancelled
        ? subscription.currentPeriodEnd &&
          `Next payment: ${freeDate(subscription.currentPeriodEnd)}`
        : deferral && renewalCancelled && freeAccess
          ? `Ends on ${freeDate(freeAccess.endsAt)}`
          : nextDateLabel(subscription)
      : null;

  return (
    <SettingsCard title="Plan">
      {loadError && <ErrorBanner message={loadError} />}
      {error && <ErrorBanner message={error} />}
      {cancelError && <ErrorBanner message={cancelError} />}
      {canceledThrough && (
        <p
          ref={cancellation}
          role="status"
          tabIndex={-1}
          className="text-sm text-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring"
        >
          Renewal cancelled. Your access stays available through {freeDate(canceledThrough)}.
        </p>
      )}
      {pending && (
        <p role="status" className="text-sm text-foreground">
          Your coupon redemption is being confirmed. Billing changes will be available when
          confirmation finishes.
        </p>
      )}
      {!data ? (
        isLoading && (
          <p role="status" className="font-sans text-sm text-muted-foreground">
            Loading your plan…
          </p>
        )
      ) : subscription ? (
        <div className="break-words rounded-lg border border-border">
          {paymentFailed && (
            <p className="border-b border-warning/30 bg-warning/10 px-4 py-2.5 font-sans text-sm text-warning">
              Your last payment failed. Update your card to keep access.
            </p>
          )}
          <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-4">
            <div className="min-w-0">
              <p className="truncate font-sans text-lg font-semibold leading-tight text-foreground">
                {deferral ? 'Your plan' : (plan?.productName ?? 'Your plan')}
              </p>
            </div>
            <Badge
              variant={statusBadgeVariant(subscription.status)}
              className="max-w-full shrink-0 break-words"
            >
              {pending
                ? 'Confirming coupon'
                : deferral
                  ? 'Free access arranged'
                  : STATUS_LABELS[subscription.status]}
            </Badge>
          </div>
          {(subscription.paidThrough || subscription.introductoryTrialEnd || freeAccess) && (
            <div className="space-y-2 border-t border-border px-4 py-3 text-sm text-foreground">
              {subscription.introductoryTrialEnd && (
                <p>Introductory trial through {freeDate(subscription.introductoryTrialEnd)}</p>
              )}
              {subscription.paidThrough && (
                <p>Paid access through {freeDate(subscription.paidThrough)}</p>
              )}
              {freeAccess?.currentStartsAt && freeAccess.currentEndsAt && (
                <p>
                  Current free access: {freeDate(freeAccess.currentStartsAt)} to{' '}
                  {freeDate(freeAccess.currentEndsAt)}
                </p>
              )}
              {freeAccess?.queuedStartsAt && (
                <p>
                  Queued free access: {freeDate(freeAccess.queuedStartsAt)} to{' '}
                  {freeDate(freeAccess.endsAt)}
                </p>
              )}
            </div>
          )}
          {data.me.futurePlan && !renewalCancelled && !billingBlocked && (
            <div className="border-t border-border px-4 py-3">
              <FuturePlanDetails plan={data.me.futurePlan} />
            </div>
          )}
          <div className="flex flex-col gap-3 border-t border-border bg-muted/40 px-4 py-3 sm:flex-row sm:flex-wrap sm:items-center sm:justify-between">
            {/* While a payment fails Stripe retries it, so nothing renews on the period end. */}
            {next && !paymentFailed && (
              <div className="space-y-2 text-sm text-foreground">
                <p>{next}</p>
                {deferral && renewalCancelled && <p>No automatic payment</p>}
              </div>
            )}
            {(deferral || data.couponsEnabled) && !renewalCancelled && (
              <div className="space-y-2 sm:max-w-64">
                <p className="text-sm text-foreground">
                  Cancel renewal to keep all remaining access with no payment afterward.
                </p>
                <Button
                  type="button"
                  variant="outline"
                  className="h-auto min-h-11 max-w-full whitespace-normal"
                  disabled={canceling || billingBlocked}
                  onClick={() => void cancelRenewal()}
                >
                  {canceling ? 'Confirming cancellation…' : 'Cancel renewal'}
                </Button>
              </div>
            )}
            {(!deferral || data.couponsEnabled) && (
              <Button
                type="button"
                disabled={billingBlocked}
                variant={paymentFailed ? 'default' : 'outline'}
                className={cn(
                  'h-auto min-h-11 max-w-full shrink-0 whitespace-normal sm:ml-auto',
                  !paymentFailed && 'bg-card',
                )}
                onClick={() => void openPortal()}
              >
                {paymentFailed
                  ? 'Fix payment'
                  : data.couponsEnabled
                    ? 'Manage billing'
                    : 'Manage subscription'}
              </Button>
            )}
          </div>
        </div>
      ) : freeAccess ? (
        <div className="space-y-2 break-words rounded-lg border border-border p-3 font-sans text-sm text-foreground sm:p-4">
          <p className="text-lg font-semibold">{data.plans[0]?.productName ?? 'Your plan'}</p>
          <Badge variant="success">Free access</Badge>
          <p className="font-semibold">Free access through {freeDate(freeAccess.endsAt)}</p>
          <p>
            Current free access: {freeDate(freeAccess.currentStartsAt ?? freeAccess.startsAt)} to{' '}
            {freeDate(freeAccess.currentEndsAt ?? freeAccess.endsAt)}
          </p>
          {freeAccess.queuedStartsAt && (
            <p>
              Queued free access: {freeDate(freeAccess.queuedStartsAt)} to{' '}
              {freeDate(freeAccess.endsAt)}
            </p>
          )}
          {!signupPending && !data.me.pendingPaidSignupId && (
            <>
              <p>No automatic payment</p>
              <p>Your free access creates no subscription or obligation to pay.</p>
            </>
          )}
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">
          No current plan. Redeem a coupon or choose a plan on the Paywall.
        </p>
      )}
      {data && (
        <PlanChange
          data={data}
          blocked={Boolean(
            pending ||
            signupPending ||
            data.me.pendingPaidSignupId ||
            canceling ||
            renewalCancelled,
          )}
          onPendingChange={setChangePending}
          onChanged={onRedeemed}
        />
      )}
      {data && !planChangePending && (
        <PaidSignup data={data} onPendingChange={setSignupPending} onArranged={onRedeemed} />
      )}
      {(data?.couponsEnabled || pending) &&
        !signupPending &&
        !data?.me.pendingPaidSignupId &&
        !planChangePending && (
          <CouponForm
            inSettings
            recoveryOnly={!data?.couponsEnabled}
            operationId={data?.me.pendingCouponOperationId}
            onPendingChange={setLocalPending}
            onRedeemed={onRedeemed}
          />
        )}
    </SettingsCard>
  );
}
