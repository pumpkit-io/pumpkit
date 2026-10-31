import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import type { CheckoutArrival, CheckoutStatus } from '@/features/billing/checkoutArrival';

/** Stripe return URLs: hand the outcome to `/` via router state, which routes by the next step. */
function BillingRedirect({ status }: { status: CheckoutStatus }) {
  const navigate = useNavigate();

  useEffect(() => {
    const timeout = window.setTimeout(() => {
      const state: CheckoutArrival = { checkoutStatus: status };
      navigate('/', { replace: true, state });
    }, 150);
    return () => window.clearTimeout(timeout);
  }, [navigate, status]);

  return (
    <div className="flex min-h-[100dvh] items-center justify-center bg-background text-foreground">
      <div role="status" className="font-sans text-sm text-muted-foreground">
        {status === 'success' ? 'Confirming your subscription…' : 'Returning to Pumpkit…'}
      </div>
    </div>
  );
}

export function BillingSuccessRedirect() {
  return <BillingRedirect status="success" />;
}

export function BillingCancelledRedirect() {
  return <BillingRedirect status="cancelled" />;
}
