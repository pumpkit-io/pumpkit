import { useEffect, useRef, useState } from 'react';
import { Button } from '@/components/ui/button';
import { ErrorBanner } from '@/components/ErrorBanner';
import { redirectTo } from '@/lib/navigation';
import { errorMessage } from '@/services/apiErrors';
import {
  billingService,
  type PaidSignupOffer,
  type TermsAcceptance,
} from '@/services/billingService';
import type { BillingData } from './BillingProvider';
import { recurringLabel } from './PlanCard';
import { TermsAcceptanceFields } from './TermsAcceptanceFields';
import { acceptsAll, NOTHING_ACCEPTED } from './termsAcceptance';
import { useBilling } from './useBilling';
import { usePaidSignup } from './usePaidSignup';

function exactDate(value: string): string {
  return `${new Date(value).toLocaleString('en-US', { dateStyle: 'long', timeStyle: 'medium', timeZone: 'UTC', hourCycle: 'h23' })} UTC`;
}

export function PaidSignup({
  data,
  onPendingChange,
  onArranged,
}: {
  data: BillingData;
  onPendingChange: (pending: boolean) => void;
  onArranged?: () => void;
}) {
  const { load } = useBilling();
  const signup = usePaidSignup(data.me.pendingPaidSignupId);
  const [expanded, setExpanded] = useState(false);
  const [offer, setOffer] = useState<PaidSignupOffer | null>(null);
  const [acceptance, setAcceptance] = useState<TermsAcceptance>(NOTHING_ACCEPTED);
  const [checking, setChecking] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const review = useRef<HTMLElement>(null);
  const status = useRef<HTMLDivElement>(null);
  const choices = useRef<HTMLDivElement>(null);
  const afterArranged = useRef(onArranged);
  afterArranged.current = onArranged;
  const wasPending = useRef(false);
  const refreshedOutcome = useRef<string | null>(null);

  useEffect(() => {
    onPendingChange(signup.pending);
    const outcome =
      signup.answer && signup.answer.status !== 'pending'
        ? `${signup.answer.operationId}:${signup.answer.status}`
        : null;
    if (
      (wasPending.current && !signup.pending) ||
      (outcome && refreshedOutcome.current !== outcome)
    ) {
      refreshedOutcome.current = outcome;
      void load();
      afterArranged.current?.();
    }
    wasPending.current = signup.pending;
  }, [signup.pending, signup.answer, onPendingChange, load]);
  useEffect(() => {
    if (offer) review.current?.focus();
  }, [offer]);
  useEffect(() => {
    if (signup.answer || signup.error) status.current?.focus();
  }, [signup.answer, signup.error]);
  useEffect(() => {
    if (expanded) choices.current?.querySelector('button')?.focus();
  }, [expanded]);

  async function preview(planKey: string) {
    setChecking(planKey);
    setError(null);
    setOffer(null);
    setAcceptance(NOTHING_ACCEPTED);
    signup.reset();
    try {
      setOffer(await billingService.previewPaidSignup(planKey));
    } catch (cause) {
      setError(errorMessage(cause, "Couldn't load the future subscription offer. Try again."));
    } finally {
      setChecking(null);
    }
  }

  async function confirm() {
    if (!offer || (offer.termsVersion && !acceptsAll(acceptance))) return;
    const result = await signup.submit({
      ...acceptance,
      operationId: crypto.randomUUID(),
      revision: offer.revision,
      termsVersion: offer.termsVersion,
      language: 'en',
    });
    if (result?.status === 'pending' && result.url) redirectTo(result.url);
    if (!result || result.status === 'refused') {
      setOffer(null);
      setAcceptance(NOTHING_ACCEPTED);
    }
  }

  const eligible = data.couponsEnabled && data.me.mayArrangePaidSignup;
  const plans = data.plans.filter(
    (plan) => plan.intervalCount === 1 && ['month', 'year'].includes(plan.interval),
  );
  if (!eligible && !signup.pending && !signup.answer && !signup.error) return null;

  return (
    <div className="space-y-3 border-t border-border pt-4 font-sans text-sm text-foreground">
      {(error || signup.error) && <ErrorBanner message={error ?? signup.error ?? ''} />}
      {(signup.pending || signup.answer) && (
        <div
          ref={status}
          role="status"
          tabIndex={-1}
          className="space-y-3 break-words focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring"
        >
          {signup.pending ? (
            <>
              <p>
                {signup.answer?.detail ??
                  'Your future subscription is not confirmed yet. Your free access and allowance stay unchanged.'}
              </p>
              <div className="flex flex-wrap gap-3">
                {signup.answer?.url && (
                  <Button
                    type="button"
                    className="h-auto min-h-11 whitespace-normal"
                    disabled={signup.busy}
                    onClick={() => {
                      if (signup.answer?.url) redirectTo(signup.answer.url);
                    }}
                  >
                    Continue checkout
                  </Button>
                )}
                <Button
                  type="button"
                  variant="outline"
                  className="h-auto min-h-11 whitespace-normal"
                  disabled={signup.busy}
                  onClick={() => void signup.check()}
                >
                  {signup.busy ? 'Checking signup…' : 'Check signup'}
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  className="h-auto min-h-11 whitespace-normal"
                  disabled={signup.busy}
                  onClick={() => void signup.cancel()}
                >
                  Cancel signup
                </Button>
              </div>
            </>
          ) : signup.answer?.status === 'completed' ? (
            <p>Subscription arranged. Your free access stays unchanged.</p>
          ) : (
            <p>
              {signup.answer?.detail ??
                'Signup ended. Your free access stays unchanged. Review a new offer to arrange a subscription.'}
            </p>
          )}
        </div>
      )}
      {eligible && !signup.pending && signup.answer?.status !== 'completed' && (
        <>
          <Button
            type="button"
            variant="outline"
            className="h-auto min-h-11 whitespace-normal"
            aria-expanded={expanded}
            onClick={() => setExpanded(!expanded)}
          >
            {expanded ? 'Close subscription choices' : 'Arrange subscription'}
          </Button>
          {expanded && (
            <div ref={choices} className="space-y-4">
              <p>
                Choose a paid plan to start after your free access. No immediate payment and no
                extra introductory trial.
              </p>
              {plans.length === 0 ? (
                <p>No monthly or yearly plans are available. Try again later.</p>
              ) : (
                <div className="grid gap-3 sm:grid-cols-2">
                  {plans.map((plan) => (
                    <div
                      key={plan.key}
                      className="min-w-0 space-y-2 rounded-lg border border-border p-3"
                    >
                      <p className="font-semibold">{plan.productName}</p>
                      <p>
                        {recurringLabel(
                          plan.amount,
                          plan.currency,
                          plan.interval,
                          plan.intervalCount,
                        )}
                      </p>
                      <Button
                        type="button"
                        variant="outline"
                        className="h-auto min-h-11 w-full whitespace-normal"
                        disabled={checking !== null || signup.busy}
                        onClick={() => void preview(plan.key)}
                      >
                        {checking === plan.key
                          ? 'Loading offer…'
                          : `Review ${plan.interval === 'month' ? 'monthly' : 'yearly'} plan`}
                      </Button>
                    </div>
                  ))}
                </div>
              )}
              {offer && (
                <section
                  ref={review}
                  tabIndex={-1}
                  aria-label="Review future subscription"
                  className="space-y-3 break-words rounded-lg border border-border p-3 focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring sm:p-4"
                >
                  <p className="font-semibold">
                    {offer.productName}:{' '}
                    {recurringLabel(
                      offer.amount,
                      offer.currency,
                      offer.interval,
                      offer.intervalCount,
                    )}
                  </p>
                  <p className="font-semibold">First payment: {exactDate(offer.firstPaymentAt)}</p>
                  <p>
                    No immediate payment. Keep all your free access through this date, then start a
                    full paid {offer.interval === 'year' ? 'year' : 'month'}. Your subscription
                    renews automatically until cancelled.
                  </p>
                  <p>
                    Continue to checkout to provide a payment method. A saved card alone does not
                    arrange a subscription.
                  </p>
                  {offer.termsVersion && (
                    <TermsAcceptanceFields value={acceptance} onChange={setAcceptance} />
                  )}
                  <Button
                    type="button"
                    className="h-auto min-h-11 max-w-full whitespace-normal"
                    disabled={signup.busy || Boolean(offer.termsVersion && !acceptsAll(acceptance))}
                    onClick={() => void confirm()}
                  >
                    {signup.busy ? 'Starting checkout…' : 'Agree and continue to checkout'}
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
