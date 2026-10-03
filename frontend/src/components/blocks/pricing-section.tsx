import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { billingService, type Price } from '@/services/billingService';
import { recurringLabel } from '@/features/billing/ProductCard';
import { track } from '@/lib/analytics';
import { useOnceVisible } from '@/lib/useOnceVisible';

type State = { status: 'loading' } | { status: 'ready'; prices: Price[] } | { status: 'error' };

export function PricingSection() {
  const [state, setState] = useState<State>({ status: 'loading' });
  const sectionRef = useRef<HTMLElement | null>(null);
  useOnceVisible(sectionRef, () => track('landing_pricing_section_viewed'));

  useEffect(() => {
    let cancelled = false;
    billingService
      .fetchPrices()
      .then(
        (prices) =>
          !cancelled && setState({ status: 'ready', prices: prices.filter((p) => p.recurring) }),
      )
      .catch(() => !cancelled && setState({ status: 'error' }));
    return () => {
      cancelled = true;
    };
  }, []);

  const prices = state.status === 'ready' ? state.prices : [];

  return (
    <section id="pricing" ref={sectionRef} className="border-t border-border bg-background py-24">
      <div className="mx-auto max-w-5xl px-6">
        <h2 className="text-center text-3xl font-normal tracking-tight text-foreground md:text-4xl">
          Pricing
        </h2>
        <p className="mt-3 text-center font-sans text-sm text-muted-foreground">
          Plans are loaded from your Stripe account (active recurring prices).
        </p>

        {state.status === 'loading' && (
          <p className="mt-12 text-center font-sans text-sm text-muted-foreground">Loading…</p>
        )}

        {(state.status === 'error' || (state.status === 'ready' && prices.length === 0)) && (
          <p className="mt-12 text-center font-sans text-sm text-muted-foreground">
            Pricing is coming soon.
          </p>
        )}

        {prices.length > 0 && (
          <div className="mt-12 grid gap-6 md:grid-cols-3">
            {prices.map((price) => (
              <div
                key={price.id}
                className="flex flex-col rounded-2xl border border-border bg-card p-6"
              >
                <h3 className="font-sans text-base font-semibold text-foreground">
                  {price.product?.name ?? 'Plan'}
                </h3>
                {price.product?.description && (
                  <p className="mt-2 font-sans text-sm text-muted-foreground">
                    {price.product.description}
                  </p>
                )}
                <div className="mt-6 font-sans text-2xl font-semibold text-foreground">
                  {recurringLabel(
                    price.unitAmount,
                    price.currency,
                    price.recurring!.interval,
                    price.recurring!.intervalCount,
                  )}
                </div>
                <Button
                  asChild
                  className="mt-6"
                  onClick={() => track('landing_pricing_cta_clicked', { price_id: price.id })}
                >
                  <Link to="/login">Get started</Link>
                </Button>
              </div>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
