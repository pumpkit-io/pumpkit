import { useEffect, useRef, useState } from 'react';
import { Button } from '@/components/ui/button';
import { ErrorBanner } from '@/components/ErrorBanner';
import { errorMessage } from '@/services/apiErrors';
import { billingService, type FuturePlan, type PlanChangeOffer } from '@/services/billingService';
import type { BillingData } from './BillingProvider';
import { recurringLabel } from './PlanCard';
import { useBilling } from './useBilling';
import { usePlanChange } from './usePlanChange';

function exactPaymentDate(value: string): string {
  return `${new Date(value).toLocaleString('en-US', { dateStyle: 'long', timeStyle: 'medium', timeZone: 'UTC', hourCycle: 'h23' })} UTC`;
}

export function FuturePlanDetails({ plan }: { plan: FuturePlan }) {
  return (
    <div className="space-y-2 break-words text-sm text-foreground">
      <p className="font-semibold">Your future plan: {plan.productName}</p>
      <p>
        {recurringLabel(plan.amount, plan.currency, plan.interval, plan.intervalCount)}, plus
        applicable tax
      </p>
      <p>Future payment: {exactPaymentDate(plan.firstPaymentAt)}</p>
      <p>
        This billing frequency starts after all remaining free access. Your allowance and remaining
        paid access stay unchanged.
      </p>
    </div>
  );
}

export function PlanChange({
  data,
  blocked,
  onPendingChange,
  onChanged,
}: {
  data: BillingData;
  blocked: boolean;
  onPendingChange: (pending: boolean) => void;
  onChanged?: () => void;
}) {
  const { load } = useBilling();
  const change = usePlanChange(data.me.pendingPlanChangeId);
  const [expanded, setExpanded] = useState(false);
  const [checking, setChecking] = useState(false);
  const [offer, setOffer] = useState<PlanChangeOffer | null>(null);
  const [error, setError] = useState<string | null>(null);
  const review = useRef<HTMLElement>(null);
  const previewError = useRef<HTMLDivElement>(null);
  const status = useRef<HTMLDivElement>(null);
  const choices = useRef<HTMLDivElement>(null);
  const refreshed = useRef<string | null>(null);
  const afterChanged = useRef(onChanged);
  afterChanged.current = onChanged;
  useEffect(() => {
    onPendingChange(change.pending);
    if (change.answer && change.answer.status !== 'pending') {
      const outcome = `${change.answer.operationId}:${change.answer.status}`;
      if (refreshed.current !== outcome) {
        refreshed.current = outcome;
        void load();
        afterChanged.current?.();
      }
    }
  }, [change.pending, change.answer, onPendingChange, load]);
  useEffect(() => {
    if (offer) review.current?.focus();
  }, [offer]);
  useEffect(() => {
    if (error) previewError.current?.focus();
  }, [error]);
  useEffect(() => {
    if (change.answer || change.error) status.current?.focus();
  }, [change.answer, change.error]);
  useEffect(() => {
    if (expanded) choices.current?.querySelector('button')?.focus();
  }, [expanded]);

  async function preview(planKey: string) {
    setChecking(true);
    setError(null);
    setOffer(null);
    change.reset();
    try {
      setOffer(await billingService.previewPlanChange(planKey));
    } catch (cause) {
      setError(errorMessage(cause, "Couldn't load this billing frequency. Try again."));
    } finally {
      setChecking(false);
    }
  }
  async function confirm() {
    if (!offer) return;
    await change.submit({ operationId: crypto.randomUUID(), revision: offer.revision });
    setOffer(null);
  }

  const eligible = data.couponsEnabled && data.me.mayChangePlan && !blocked;
  const current = data.plans.find((p) => p.key === data.me.subscription?.planKey);
  const plans = data.plans.filter(
    (p) =>
      p.intervalCount === 1 &&
      ['month', 'year'].includes(p.interval) &&
      p.key !== current?.key &&
      (!current || p.interval !== current.interval),
  );
  if (!eligible && !change.pending && !change.answer && !change.error) return null;
  return (
    <div className="space-y-3 border-t border-border pt-4 font-sans text-sm text-foreground">
      {error && (
        <div
          ref={previewError}
          tabIndex={-1}
          className="focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring"
        >
          <ErrorBanner message={error} />
        </div>
      )}
      {(change.pending || change.answer || change.error) && (
        <div
          ref={status}
          role="status"
          tabIndex={-1}
          className="space-y-3 break-words focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring"
        >
          {change.error && <ErrorBanner message={change.error} />}
          {change.pending ? (
            <>
              <p>
                {change.answer?.detail ??
                  'Confirming your billing frequency. Your paid and free access stay unchanged.'}
              </p>
              <Button
                type="button"
                variant="outline"
                className="h-auto min-h-11 whitespace-normal"
                disabled={change.busy}
                onClick={() => void change.check()}
              >
                {change.busy ? 'Checking change…' : 'Check billing change'}
              </Button>
            </>
          ) : change.answer?.status === 'completed' ? (
            <p>Billing frequency changed. Your paid and free access stay unchanged.</p>
          ) : change.answer ? (
            <p>
              {change.answer.detail ??
                'The billing frequency was not changed. Review a fresh offer to try again.'}
            </p>
          ) : null}
        </div>
      )}
      {eligible && !change.pending && (
        <>
          <Button
            type="button"
            variant="outline"
            className="h-auto min-h-11 whitespace-normal"
            aria-expanded={expanded}
            onClick={() => setExpanded(!expanded)}
          >
            {expanded ? 'Close billing choices' : 'Change billing frequency'}
          </Button>
          {expanded && (
            <div ref={choices} className="space-y-4">
              <p>
                Change the billing frequency after your free access. No immediate payment; all
                remaining paid and free time stays available.
              </p>
              {plans.length ? (
                <div className="flex flex-wrap gap-3">
                  {plans.map((plan) => (
                    <Button
                      key={plan.key}
                      type="button"
                      variant="outline"
                      className="h-auto min-h-11 max-w-full whitespace-normal"
                      disabled={checking || change.busy}
                      onClick={() => void preview(plan.key)}
                    >
                      {checking
                        ? 'Loading offer…'
                        : `Review ${plan.interval === 'month' ? 'monthly' : 'yearly'} plan`}
                    </Button>
                  ))}
                </div>
              ) : (
                <p>No other monthly or yearly plan is available. Try again later.</p>
              )}
              {offer && (
                <section
                  ref={review}
                  tabIndex={-1}
                  aria-label="Review billing frequency"
                  className="space-y-3 rounded-lg border border-border p-3 focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring"
                >
                  <FuturePlanDetails plan={offer} />
                  <p>
                    No immediate payment. Your first full payment uses the amount and date above.
                  </p>
                  <Button
                    type="button"
                    className="h-auto min-h-11 w-full whitespace-normal"
                    disabled={change.busy || blocked}
                    onClick={() => void confirm()}
                  >
                    {change.busy ? 'Confirming change…' : 'Confirm billing frequency'}
                  </Button>
                </section>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
