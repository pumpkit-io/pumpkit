import { useState } from 'react';
import { ErrorBanner } from '@/components/ErrorBanner';
import { SettingsCard } from '@/components/SettingsCard';
import { track } from '@/lib/analytics';
import { redirectTo } from '@/lib/navigation';
import { errorMessage } from '@/services/apiErrors';
import { billingService, type TermsAcceptance } from '@/services/billingService';
import type { BillingData } from './BillingProvider';
import { CHOOSE_PLAN_ID } from './choosePlan';
import { PlanCard, recurringLabel } from './PlanCard';
import { OfferLineContent } from './OfferLineContent';
import { offerLines } from './planOffer';
import { acceptsAll, NOTHING_ACCEPTED } from './termsAcceptance';
import { TermsAcceptanceFields } from './TermsAcceptanceFields';

/**
 * The Plans, behind the Terms boxes (ADR 0010). Remount with a new `key` per Terms version.
 * `notice` is the error it opens with, such as a cancelled checkout.
 */
export function ChoosePlanCard({ data, notice }: { data: BillingData; notice: string | null }) {
  const [acceptance, setAcceptance] = useState<TermsAcceptance>(NOTHING_ACCEPTED);
  const [pendingKey, setPendingKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(notice);
  const hasTerms = data.termsVersion !== null;
  const accepted = !hasTerms || acceptsAll(acceptance);
  const trialDays = data.me.trialDays;
  const offer = offerLines(data.allowance, trialDays === null ? null : data.trial);

  const subscribe = async (planKey: string) => {
    track('billing_subscription_checkout_started', { plan_key: planKey });
    setPendingKey(planKey);
    setError(null);
    try {
      redirectTo(
        await billingService.startSubscriptionCheckout(planKey, data.termsVersion, acceptance),
      );
    } catch (e) {
      const message = errorMessage(e, "Couldn't start checkout. Try again.");
      track('billing_checkout_redirect_failed', { error_message: message });
      setError(message);
      setPendingKey(null);
    }
  };

  return (
    <SettingsCard
      id={CHOOSE_PLAN_ID}
      title="Choose a plan"
      description="Writing, scheduling and your persona need a subscription."
      className="border-primary/40"
    >
      {error && <ErrorBanner message={error} />}
      {data.plans.length === 0 ? (
        <p className="font-sans text-sm text-muted-foreground">No plans are available yet.</p>
      ) : (
        <>
          <ul aria-label="Included" className="space-y-1.5 font-sans text-sm text-foreground">
            {offer.map((line) => (
              <li key={line.text}>
                <OfferLineContent line={line} />
              </li>
            ))}
          </ul>
          {hasTerms && (
            <div className="space-y-2">
              <p className="font-sans text-xs text-muted-foreground">
                Tick the three boxes, then choose a plan.
              </p>
              <TermsAcceptanceFields value={acceptance} onChange={setAcceptance} />
            </div>
          )}
          <div className="grid gap-3 sm:grid-cols-2">
            {data.plans.map((plan) => {
              const action = trialDays === null ? 'Subscribe' : 'Start free trial';
              return (
                <PlanCard
                  key={plan.key}
                  title={plan.productName}
                  priceLabel={recurringLabel(
                    plan.amount,
                    plan.currency,
                    plan.interval,
                    plan.intervalCount,
                  )}
                  actionLabel={pendingKey === plan.key ? 'Redirecting…' : action}
                  ariaLabel={`${trialDays === null ? 'Subscribe to' : 'Start free trial of'} ${plan.productName}`}
                  disabled={!accepted || pendingKey !== null}
                  onAction={() => void subscribe(plan.key)}
                />
              );
            })}
          </div>
        </>
      )}
    </SettingsCard>
  );
}
