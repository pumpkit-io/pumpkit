import { useEffect, useRef, useState, type ReactNode } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { ErrorBanner } from '@/components/ErrorBanner';
import { LimitNotice } from '@/components/LimitNotice';
import { Button } from '@/components/ui/button';
import { BillingProvider, type BillingData } from '@/features/billing/BillingProvider';
import { checkoutStatusOf } from '@/features/billing/checkoutArrival';
import { PlanPicker } from '@/features/billing/PlanPicker';
import { useBilling } from '@/features/billing/useBilling';
import { track } from '@/lib/analytics';
import { redirectTo } from '@/lib/navigation';
import { errorMessage } from '@/services/apiErrors';
import { billingService } from '@/services/billingService';

const CHECKOUT_CANCELLED = "Checkout cancelled. Pick a plan when you're ready.";

/** Takes a cancelled checkout from the location state once, so a reload doesn't repeat it. */
function useCancelledArrival(): boolean {
  const location = useLocation();
  const navigate = useNavigate();
  const [cancelled] = useState(() => checkoutStatusOf(location.state) === 'cancelled');
  useEffect(() => {
    if (cancelled) navigate(location.pathname, { replace: true, state: null });
  }, [cancelled, navigate, location.pathname]);
  return cancelled;
}

function useViewedOnce() {
  const tracked = useRef(false);
  useEffect(() => {
    if (tracked.current) return;
    tracked.current = true;
    track('paywall_viewed');
  }, []);
}

/** The day a Trial starting today ends and the first charge falls, e.g. "14 Nov 2026". */
function firstChargeDate(trialDays: number): string {
  const date = new Date();
  date.setDate(date.getDate() + trialDays);
  return date.toLocaleDateString(undefined, { dateStyle: 'medium' });
}

function Heading({ title, lead }: { title: string; lead?: string }) {
  return (
    <div className="max-w-[560px] space-y-2">
      <h1 className="font-sans text-2xl/[30px] font-semibold tracking-[-0.015em] text-foreground">
        {title}
      </h1>
      {lead && <p className="font-sans text-sm text-muted-foreground">{lead}</p>}
    </div>
  );
}

/** Where the billing portal is the only way forward: a payment still processing, or one failed. */
function PortalState({ title, lead }: { title: string; lead: string }) {
  const [error, setError] = useState<string | null>(null);
  const [opening, setOpening] = useState(false);

  const openPortal = async () => {
    setError(null);
    setOpening(true);
    try {
      const url = await billingService.openBillingPortal();
      track('billing_portal_opened');
      redirectTo(url);
    } catch (e) {
      setError(errorMessage(e, "Couldn't open the billing portal. Try again."));
      setOpening(false);
    }
  };

  return (
    <div className="space-y-5">
      <Heading title={title} lead={lead} />
      {error && <ErrorBanner message={error} />}
      <Button type="button" disabled={opening} onClick={() => void openPortal()}>
        {opening ? 'Opening…' : 'Open billing portal'}
      </Button>
    </div>
  );
}

function PlanSkeleton() {
  return (
    <div role="status" aria-label="Loading plans" className="grid gap-3 sm:grid-cols-2">
      {[0, 1].map((i) => (
        <div
          key={i}
          className="h-[164px] animate-pulse rounded-xl bg-muted motion-reduce:animate-none"
        />
      ))}
    </div>
  );
}

function Offer({ data, notice }: { data: BillingData; notice: ReactNode }) {
  const { trialDays } = data.me;
  return (
    <div className="space-y-6">
      {trialDays !== null ? (
        <Heading
          title="Start your free trial"
          lead={`${trialDays} days free, then billed by the plan you pick.`}
        />
      ) : (
        <Heading title="Subscribe to keep writing" lead="Pick a plan to use Pumpkit again." />
      )}
      {notice}
      <PlanPicker
        // A new Terms version must be accepted afresh.
        key={data.termsVersion}
        data={data}
        actionLabel={trialDays !== null ? 'Start trial' : 'Subscribe'}
      />
      {trialDays !== null && (
        <p className="font-sans text-sm text-foreground">
          You won&apos;t be charged until {firstChargeDate(trialDays)}.
        </p>
      )}
    </div>
  );
}

function PaywallContent() {
  const { data, isLoading, loadError, load } = useBilling();
  const cancelled = useCancelledArrival();
  useViewedOnce();

  useEffect(() => {
    void load();
  }, [load]);

  if (loadError) {
    return (
      <div className="space-y-5">
        <Heading title="Choose a plan" />
        <ErrorBanner message="Couldn't load plans." onRetry={() => void load()} />
      </div>
    );
  }
  if (!data || isLoading) {
    return (
      <div className="space-y-6">
        <Heading title="Choose a plan" />
        <PlanSkeleton />
      </div>
    );
  }
  const status = data.me.subscription?.status;
  if (status === 'incomplete') {
    return (
      <PortalState
        title="Your payment is still processing."
        lead="Open the billing portal to see where it stands. You don't need to check out again."
      />
    );
  }
  if (!data.me.maySubscribe) {
    return (
      <PortalState
        title="Your subscription is on hold"
        lead="Your last payment failed. Update your card in the billing portal to keep writing."
      />
    );
  }
  return (
    <Offer data={data} notice={cancelled ? <LimitNotice message={CHECKOUT_CANCELLED} /> : null} />
  );
}

/** `/subscribe`: the only page a signed-in User who isn't Subscribed sees (ADR 0018). */
export function Paywall() {
  return (
    <BillingProvider>
      <PaywallContent />
    </BillingProvider>
  );
}
