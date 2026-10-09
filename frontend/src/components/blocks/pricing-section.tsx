import { useEffect, useId, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { CtaFrame } from '@/components/blocks/cta-frame';
import { Eyebrow } from '@/components/blocks/eyebrow';
import { Button } from '@/components/ui/button';
import { Table, TableBody, TableCell, TableRow } from '@/components/ui/table';
import { billingService, type Plan } from '@/services/billingService';
import { recurringLabel } from '@/features/billing/PlanCard';
import { track } from '@/lib/analytics';
import { useOnceVisible } from '@/lib/useOnceVisible';

type State = { status: 'loading' } | { status: 'ready'; plans: Plan[] } | { status: 'error' };

// Placeholder contents, the same for every Plan until real copy exists.
const PLAN_INCLUDES = [
  '[What this Plan includes]',
  '[What this Plan includes]',
  '[What this Plan includes]',
];

function PlanTable({ plan }: { plan: Plan }) {
  const planRef = useRef<HTMLDivElement | null>(null);
  const headingId = useId();
  useOnceVisible(planRef, () => track('landing_pricing_plan_viewed', { plan_key: plan.key }));

  return (
    <div ref={planRef}>
      <h3 id={headingId} className="mb-3 text-left text-lg font-medium text-foreground md:text-xl">
        <strong className="font-semibold">
          {recurringLabel(plan.amount, plan.currency, plan.interval, plan.intervalCount)}
        </strong>{' '}
        gets you:
      </h3>
      <Table aria-labelledby={headingId}>
        <TableBody>
          {PLAN_INCLUDES.map((item, i) => (
            <TableRow key={i} index={i}>
              <TableCell className="py-5 text-base md:text-lg">{item}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
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
      .then((plans) => !cancelled && setState({ status: 'ready', plans }))
      .catch(() => !cancelled && setState({ status: 'error' }));
    return () => {
      cancelled = true;
    };
  }, []);

  const plans = state.status === 'ready' ? state.plans : [];

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
      <div className="mx-auto max-w-4xl px-6">
        <div className="text-center">
          <Eyebrow>Pricing</Eyebrow>
          <h2
            id={headingId}
            className="mt-3 text-balance text-4xl font-semibold tracking-tight md:text-5xl"
          >
            Simple pricing
          </h2>
          <p className="mx-auto mt-4 max-w-2xl text-base text-muted-foreground md:text-lg">
            [Pricing subline]
          </p>
        </div>

        {state.status === 'loading' && (
          <p className="mt-14 text-center text-sm text-muted-foreground">Loading…</p>
        )}

        {state.status === 'error' && (
          <p className="mt-14 text-center text-sm text-muted-foreground">
            Pricing couldn't load. Refresh the page to try again.
          </p>
        )}

        {state.status === 'ready' && plans.length === 0 && (
          <p className="mt-14 text-center text-sm text-muted-foreground">Pricing is coming soon.</p>
        )}

        {plans.length > 0 && (
          <div className="mt-14 flex flex-col gap-12">
            {plans.map((plan) => (
              <PlanTable key={plan.key} plan={plan} />
            ))}
          </div>
        )}

        <div className="mt-14 flex justify-center">
          <CtaFrame>
            <Button asChild size="lg" className="rounded-xl px-6 text-base">
              <Link to="/login" onClick={() => track('landing_pricing_cta_clicked')}>
                Get started
              </Link>
            </Button>
          </CtaFrame>
        </div>
      </div>
    </section>
  );
}
