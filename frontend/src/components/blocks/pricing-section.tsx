import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { billingService, type Plan } from '@/services/billingService';
import { recurringLabel } from '@/features/billing/PlanCard';
import { track } from '@/lib/analytics';
import { useOnceVisible } from '@/lib/useOnceVisible';

type State = { status: 'loading' } | { status: 'ready'; plans: Plan[] } | { status: 'error' };

export function PricingSection() {
  const [state, setState] = useState<State>({ status: 'loading' });
  const sectionRef = useRef<HTMLElement | null>(null);
  useOnceVisible(sectionRef, () => track('landing_pricing_section_viewed'));

  useEffect(() => {
    let cancelled = false;
    billingService
      .fetchPlans()
      .then((plans) => !cancelled && setState({ status: 'ready', plans }))
      .catch(() => !cancelled && setState({ status: 'error' }));
    return () => {
      cancelled = true;
    };
  }, []);

  const plans = state.status === 'ready' ? state.plans : [];

  return (
    <section id="pricing" ref={sectionRef} className="border-t border-border bg-background py-24">
      <div className="mx-auto max-w-5xl px-6">
        <h2 className="text-center text-3xl font-normal tracking-tight text-foreground md:text-4xl">
          Pricing
        </h2>
        <p className="mt-3 text-center font-sans text-sm text-muted-foreground">
          Pick a Plan, billed through Stripe. Cancel anytime from the billing portal.
        </p>

        {state.status === 'loading' && (
          <p className="mt-12 text-center font-sans text-sm text-muted-foreground">Loading…</p>
        )}

        {state.status === 'error' && (
          <p className="mt-12 text-center font-sans text-sm text-muted-foreground">
            Pricing couldn't load. Refresh the page to try again.
          </p>
        )}

        {state.status === 'ready' && plans.length === 0 && (
          <p className="mt-12 text-center font-sans text-sm text-muted-foreground">
            Pricing is coming soon.
          </p>
        )}

        {plans.length > 0 && (
          <div className="mt-12 flex flex-wrap justify-center gap-6">
            {plans.map((plan) => (
              <div
                key={plan.key}
                className="flex w-full flex-col rounded-2xl border border-border bg-card p-6 md:w-72"
              >
                <h3 className="font-sans text-base font-semibold text-foreground">
                  {plan.productName}
                </h3>
                <div className="mt-6 font-sans text-2xl font-semibold text-foreground">
                  {recurringLabel(plan.amount, plan.currency, plan.interval, plan.intervalCount)}
                </div>
                <Button
                  asChild
                  className="mt-6"
                  onClick={() => track('landing_pricing_cta_clicked', { plan_key: plan.key })}
                >
                  <Link to="/login">Sign in to subscribe</Link>
                </Button>
              </div>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
