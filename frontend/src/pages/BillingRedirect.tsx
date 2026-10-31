import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import type { SettingsLocationState } from './Settings';

type BillingRedirectStatus = NonNullable<SettingsLocationState['checkoutStatus']>;

/** Stripe return URLs: hand the outcome to Settings via router state, then go there. */
function BillingRedirect({ status }: { status: BillingRedirectStatus }) {
  const navigate = useNavigate();

  useEffect(() => {
    const timeout = window.setTimeout(() => {
      const state: SettingsLocationState = { checkoutStatus: status };
      navigate('/settings', { replace: true, state });
    }, 150);
    return () => window.clearTimeout(timeout);
  }, [navigate, status]);

  return (
    <div className="flex min-h-[100dvh] items-center justify-center bg-background text-foreground">
      <div role="status" className="font-sans text-sm text-muted-foreground">
        {status === 'success'
          ? 'Confirming your subscription…'
          : status === 'top_up_bought'
            ? 'Confirming your top-up…'
            : 'Returning to Settings…'}
      </div>
    </div>
  );
}

export function BillingSuccessRedirect() {
  return <BillingRedirect status="success" />;
}

export function TopUpBoughtRedirect() {
  return <BillingRedirect status="top_up_bought" />;
}

export function BillingCancelledRedirect() {
  return <BillingRedirect status="cancelled" />;
}
