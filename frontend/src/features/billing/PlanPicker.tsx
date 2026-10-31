import { useState } from 'react';
import { ErrorBanner } from '@/components/ErrorBanner';
import { track } from '@/lib/analytics';
import { redirectTo } from '@/lib/navigation';
import { errorMessage } from '@/services/apiErrors';
import { billingService, type Plan, type TermsAcceptance } from '@/services/billingService';
import type { BillingData } from './BillingProvider';
import { OfferLineContent } from './OfferLineContent';
import { PlanCard, recurringLabel } from './PlanCard';
import { offerLines } from './planOffer';
import { acceptsAll, NOTHING_ACCEPTED } from './termsAcceptance';
import { TermsAcceptanceFields } from './TermsAcceptanceFields';

function monthsIn(plan: Plan): number | null {
  if (plan.interval === 'month') return plan.intervalCount;
  if (plan.interval === 'year') return 12 * plan.intervalCount;
  return null;
}

/** "Monthly" or "Yearly", since the Plans may share one product name; else the product's name. */
function planTitle(plan: Plan): string {
  if (plan.intervalCount === 1 && plan.interval === 'month') return 'Monthly';
  if (plan.intervalCount === 1 && plan.interval === 'year') return 'Yearly';
  return plan.productName;
}

/** What `plan` saves over paying `monthly` for as long, e.g. "Saves 17% vs monthly". */
function savingOver(plan: Plan, monthly: Plan | undefined): string | undefined {
  const months = monthsIn(plan);
  if (!monthly || plan === monthly || months === null || plan.currency !== monthly.currency) {
    return undefined;
  }
  const percent = Math.round((1 - plan.amount / (monthly.amount * months)) * 100);
  return percent > 0 ? `Saves ${percent}% vs monthly` : undefined;
}

/**
 * What a Plan includes, the Plans side by side, then the Terms boxes (ADR 0010), and checkout on a pick. Remount with a
 * new `key` per Terms version. `actionLabel` names the button: a Trial or a plain Subscription.
 */
export function PlanPicker({
  data,
  actionLabel,
}: {
  data: BillingData;
  actionLabel: 'Start trial' | 'Subscribe';
}) {
  const [acceptance, setAcceptance] = useState<TermsAcceptance>(NOTHING_ACCEPTED);
  const [pendingKey, setPendingKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const hasTerms = data.termsVersion !== null;
  const accepted = !hasTerms || acceptsAll(acceptance);
  const monthly = data.plans.find((plan) => plan.interval === 'month' && plan.intervalCount === 1);
  const offer = offerLines(data.allowance, data.me.trialDays === null ? null : data.trial);

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

  if (data.plans.length === 0) {
    return <p className="font-sans text-sm text-muted-foreground">No plans are available yet.</p>;
  }

  return (
    <div className="space-y-5">
      {error && <ErrorBanner message={error} />}
      <ul aria-label="Included" className="space-y-1.5 font-sans text-sm text-foreground">
        {offer.map((line) => (
          <li key={line.text}>
            <OfferLineContent line={line} />
          </li>
        ))}
      </ul>
      <div className="grid gap-3 sm:grid-cols-2">
        {data.plans.map((plan) => (
          <PlanCard
            key={plan.key}
            title={planTitle(plan)}
            priceLabel={recurringLabel(
              plan.amount,
              plan.currency,
              plan.interval,
              plan.intervalCount,
            )}
            note={savingOver(plan, monthly)}
            actionLabel={pendingKey === plan.key ? 'Redirecting…' : actionLabel}
            ariaLabel={`${actionLabel}: ${planTitle(plan)}`}
            disabled={!accepted || pendingKey !== null}
            onAction={() => void subscribe(plan.key)}
          />
        ))}
      </div>
      {hasTerms && (
        <div className="space-y-2">
          <p className="font-sans text-xs text-muted-foreground">
            Tick the three boxes, then choose a plan.
          </p>
          <TermsAcceptanceFields value={acceptance} onChange={setAcceptance} />
        </div>
      )}
    </div>
  );
}
