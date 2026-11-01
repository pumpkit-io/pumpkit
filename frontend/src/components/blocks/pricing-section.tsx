import { useEffect, useId, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { CtaFrame } from '@/components/blocks/cta-frame';
import { Mascot } from '@/components/blocks/mascot';
import { Button } from '@/components/ui/button';
import { billingService, type Plan, type PlanCatalog } from '@/services/billingService';
import { OfferLineContent } from '@/features/billing/OfferLineContent';
import { offerLines, trialLine } from '@/features/billing/planOffer';
import { track } from '@/lib/analytics';
import { formatPrice } from '@/lib/money';
import { useOnceVisible } from '@/lib/useOnceVisible';
import { cn } from '@/lib/utils';

type State =
  { status: 'loading' } | { status: 'ready'; catalog: PlanCatalog } | { status: 'error' };

type Interval = 'monthly' | 'annual';

interface PlanPair {
  monthly: Plan;
  annual: Plan;
}

const isEvery = (plan: Plan, interval: string) =>
  plan.interval === interval && plan.intervalCount === 1;

/** The monthly and the annual Plan, when the catalogue holds exactly those two. */
function monthlyAndAnnual(plans: Plan[]): PlanPair | null {
  const monthly = plans.filter((plan) => isEvery(plan, 'month'));
  const annual = plans.filter((plan) => isEvery(plan, 'year'));
  if (plans.length !== 2 || monthly.length !== 1 || annual.length !== 1) return null;
  return { monthly: monthly[0], annual: annual[0] };
}

/** What a year of the annual Plan saves over twelve months of the monthly one, in whole percent. */
function savingPercent({ monthly, annual }: PlanPair): number | null {
  if (monthly.currency !== annual.currency) return null;
  const percent = Math.round((1 - annual.amount / (12 * monthly.amount)) * 100);
  return percent > 0 ? percent : null;
}

/** "€19 a month", "€190 a year" or "€24 every 3 months". */
function PriceLine({ plan }: { plan: Plan }) {
  const every =
    plan.intervalCount === 1
      ? `a ${plan.interval}`
      : `every ${plan.intervalCount} ${plan.interval}s`;
  return (
    <p className="text-lg text-muted-foreground">
      <span className="text-5xl font-semibold tracking-tight text-foreground">
        {formatPrice(plan.amount, plan.currency)}
      </span>{' '}
      {every}
    </p>
  );
}

function IntervalToggle({
  value,
  saving,
  onChange,
}: {
  value: Interval;
  saving: number | null;
  onChange: (interval: Interval) => void;
}) {
  const name = useId();
  const options: { interval: Interval; label: string }[] = [
    { interval: 'monthly', label: 'Monthly' },
    { interval: 'annual', label: 'Annual' },
  ];

  return (
    <div
      role="radiogroup"
      aria-label="Billing interval"
      className="relative inline-grid grid-cols-2 rounded-xl border border-border bg-muted p-1"
    >
      {/* One thumb slides under both options, so a change shows which way it went. */}
      <span
        aria-hidden
        className={cn(
          'absolute inset-y-1 left-1 w-[calc(50%-4px)] rounded-lg bg-primary shadow-raised transition-transform duration-200 ease-out motion-reduce:transition-none',
          value === 'annual' && 'translate-x-full',
        )}
      />
      {options.map((option) => (
        <label
          key={option.interval}
          className={cn(
            'relative flex cursor-pointer items-center justify-center gap-1.5 whitespace-nowrap rounded-lg px-2.5 py-2 sm:gap-2 sm:px-4 text-sm font-medium transition-colors duration-200 motion-reduce:transition-none has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-ring has-[:focus-visible]:ring-offset-2 has-[:focus-visible]:ring-offset-background',
            value === option.interval
              ? 'text-primary-foreground'
              : 'text-muted-foreground hover:text-foreground',
          )}
        >
          <input
            type="radio"
            name={name}
            value={option.interval}
            checked={value === option.interval}
            onChange={() => onChange(option.interval)}
            className="sr-only"
          />
          {option.label}
          {option.interval === 'annual' && saving !== null && (
            <span className="rounded-full border border-current px-1.5 text-xs leading-5">
              Save {saving}%
            </span>
          )}
        </label>
      ))}
    </div>
  );
}

function PricingCta() {
  return (
    <CtaFrame>
      <Button asChild size="lg" className="rounded-xl px-6 text-base">
        <Link to="/login" onClick={() => track('landing_pricing_cta_clicked')}>
          Get started
        </Link>
      </Button>
    </CtaFrame>
  );
}

/** The one pricing card: a Monthly/Annual toggle over a pair of Plans, else each Plan's price. */
function PricingCard({ catalog }: { catalog: PlanCatalog }) {
  const pair = monthlyAndAnnual(catalog.plans);
  const [interval, setBillingInterval] = useState<Interval>('monthly');
  const cardRef = useRef<HTMLDivElement | null>(null);
  const plansFor = (value: Interval) =>
    pair ? [value === 'monthly' ? pair.monthly : pair.annual] : catalog.plans;
  const shown = plansFor(interval);

  const cardSeenRef = useRef(false);
  const viewedKeysRef = useRef(new Set<string>());
  const trackViewed = (plans: Plan[]) => {
    for (const plan of plans) {
      if (viewedKeysRef.current.has(plan.key)) continue;
      viewedKeysRef.current.add(plan.key);
      track('landing_pricing_plan_viewed', { plan_key: plan.key });
    }
  };
  useOnceVisible(cardRef, () => {
    cardSeenRef.current = true;
    trackViewed(shown);
  });

  const [celebrations, setCelebrations] = useState(0);
  const choose = (next: Interval) => {
    setBillingInterval(next);
    if (cardSeenRef.current) trackViewed(plansFor(next));
    if (next === 'annual') setCelebrations((count) => (count === 0 ? 1 : count));
    track('landing_pricing_toggle_switched', { interval: next });
  };

  const offer = offerLines(catalog.allowance, null);

  return (
    <div className="mt-10 flex flex-col items-center gap-6">
      {pair && <IntervalToggle value={interval} saving={savingPercent(pair)} onChange={choose} />}
      <div
        ref={cardRef}
        className="relative w-full max-w-md rounded-2xl border border-border bg-card p-6 text-left shadow-panel sm:p-8"
      >
        <div className="space-y-1">
          {shown.map((plan) => (
            <PriceLine key={plan.key} plan={plan} />
          ))}
          {pair && interval === 'annual' && (
            <p className="text-sm text-muted-foreground">
              {formatPrice(Math.round(pair.annual.amount / 12), pair.annual.currency)} a month,
              billed yearly
            </p>
          )}
        </div>
        {catalog.trial && (
          <p className="mt-4 text-sm text-muted-foreground">{trialLine(catalog.trial)}</p>
        )}
        <ul
          aria-label="Included"
          className="mt-6 space-y-3 border-t border-border pt-6 text-base text-foreground"
        >
          {offer.map((line) => (
            <li key={line.text}>
              <OfferLineContent line={line} />
            </li>
          ))}
        </ul>
        <div className="mt-8 flex justify-center">
          <PricingCta />
        </div>
        <Mascot
          animation="tada"
          playInViewAfterMs={null}
          trigger={celebrations}
          mdScale={2}
          className="absolute bottom-3 right-3 sm:bottom-4 sm:right-4"
        />
      </div>
    </div>
  );
}

export function PricingSection() {
  const [state, setState] = useState<State>({ status: 'loading' });
  const sectionRef = useRef<HTMLElement | null>(null);
  const headingId = useId();
  useOnceVisible(sectionRef, () => track('landing_pricing_section_viewed'));

  useEffect(() => {
    let cancelled = false;
    billingService
      .fetchPlans()
      .then((catalog) => !cancelled && setState({ status: 'ready', catalog }))
      .catch(() => !cancelled && setState({ status: 'error' }));
    return () => {
      cancelled = true;
    };
  }, []);

  const message =
    state.status === 'loading'
      ? 'Loading…'
      : state.status === 'error'
        ? "Pricing couldn't load. Refresh the page to try again."
        : state.catalog.plans.length === 0
          ? 'Pricing is coming soon.'
          : null;

  return (
    <section
      ref={sectionRef}
      id="pricing"
      aria-labelledby={headingId}
      className="relative scroll-mt-24 bg-background pb-24 pt-16 md:pb-32 md:pt-24"
    >
      <div
        aria-hidden
        className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-border to-transparent"
      />
      <div className="mx-auto max-w-4xl px-4 text-center sm:px-6">
        <h2
          id={headingId}
          className="text-balance font-display text-4xl font-semibold tracking-tight md:text-5xl"
        >
          One plan. Everything in it.
        </h2>

        {state.status === 'ready' && message === null && <PricingCard catalog={state.catalog} />}

        {message !== null && (
          <>
            <p className="mt-14 text-sm text-muted-foreground">{message}</p>
            <div className="mt-14 flex justify-center">
              <PricingCta />
            </div>
          </>
        )}
      </div>
    </section>
  );
}
