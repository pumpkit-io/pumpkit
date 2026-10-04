import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';

type BillingRedirectStatus = 'success' | 'cancelled';

/** Stripe return URLs: hand the outcome to /home via router state, then go there. */
function BillingRedirect({ status }: { status: BillingRedirectStatus }) {
  const navigate = useNavigate();

  useEffect(() => {
    const timeout = window.setTimeout(() => {
      navigate('/home', { replace: true, state: { checkoutStatus: status } });
    }, 150);
    return () => window.clearTimeout(timeout);
  }, [navigate, status]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-background text-foreground">
      <div className="font-sans text-sm text-muted-foreground">
        {status === 'success' ? 'Confirming your subscription…' : 'Returning home…'}
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
