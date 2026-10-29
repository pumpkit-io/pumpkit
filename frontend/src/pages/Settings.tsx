import { useEffect, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { useAuth } from '@/contexts/AuthContext';
import { ProfileCard } from '@/features/account/ProfileCard';
import { ApiKeysSection } from '@/features/apiKeys/ApiKeysSection';
import { ChoosePlanCard } from '@/features/billing/ChoosePlanCard';
import { CHOOSE_PLAN_ID } from '@/features/billing/choosePlan';
import { SubscriptionCard } from '@/features/billing/SubscriptionCard';
import { useBilling } from '@/features/billing/useBilling';
import { useInstance } from '@/features/instance/useInstance';
import { LegalLinks } from '@/features/legal/LegalLinks';
import { AppearanceCard } from '@/features/theme/AppearanceCard';
import { Topbar } from '@/features/topbar/Topbar';
import { XAccountCard } from '@/features/xConnection/XAccountCard';
import { track } from '@/lib/analytics';
import { fireSuccessConfetti } from '@/lib/confetti';

/** What the X callback and the Stripe return routes leave in the location state for Settings. */
export interface SettingsLocationState {
  xConnectionNotice?: string;
  checkoutStatus?: 'success' | 'cancelled';
}

const CHECKOUT_CANCELLED = 'Checkout was cancelled. You have not been charged.';

const LEGAL_LINK_CLASS =
  'rounded-sm underline-offset-4 transition-colors hover:text-foreground hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring';

/** Takes the location state once, then drops it so a reload doesn't show it again. */
function useArrivalState(): SettingsLocationState {
  const location = useLocation();
  const navigate = useNavigate();
  const [arrival] = useState(() => ({
    state: (location.state as SettingsLocationState | null) ?? {},
    hash: location.hash,
  }));

  useEffect(() => {
    if (arrival.state.xConnectionNotice || arrival.state.checkoutStatus) {
      navigate({ hash: arrival.hash }, { replace: true, state: null });
    }
  }, [arrival, navigate]);

  return arrival.state;
}

/** Loads billing on every visit, since Stripe changes it outside the app, and greets a checkout. */
function useBillingOnArrival(checkoutStatus: SettingsLocationState['checkoutStatus']) {
  const { sells_plans } = useInstance();
  const { load } = useBilling();
  // StrictMode runs effects twice in development, and a checkout is greeted once.
  const greeted = useRef(false);

  useEffect(() => {
    if (!sells_plans) return;
    void load();
    if (greeted.current) return;
    greeted.current = true;
    if (checkoutStatus === 'success') {
      track('billing_checkout_succeeded');
      fireSuccessConfetti(null);
    } else if (checkoutStatus === 'cancelled') {
      track('billing_checkout_cancelled');
    }
  }, [sells_plans, load, checkoutStatus]);
}

/** Scrolls to Choose a Plan once it is on screen, for the prompts that link to it. */
function useScrollToChoosePlan(shown: boolean) {
  const { hash } = useLocation();
  useEffect(() => {
    if (shown && hash === `#${CHOOSE_PLAN_ID}`) {
      document.getElementById(CHOOSE_PLAN_ID)?.scrollIntoView?.({ block: 'start' });
    }
  }, [shown, hash]);
}

/** Rendered inside AppLayout: the User's account as one column of cards. */
export function Settings() {
  const { logout } = useAuth();
  const { sells_plans } = useInstance();
  const billing = useBilling();
  const arrival = useArrivalState();
  useBillingOnArrival(arrival.checkoutStatus);

  const data = billing.data;
  const choosesPlan = sells_plans && data !== null && data.me.maySubscribe;
  useScrollToChoosePlan(choosesPlan);

  return (
    <>
      <Topbar
        title="Settings"
        actions={
          <Button
            variant="outline"
            size="sm"
            className="h-9"
            onClick={() => {
              track('settings_sign_out_clicked');
              void logout();
            }}
          >
            Sign out
          </Button>
        }
      />
      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto flex w-full max-w-2xl flex-col gap-4 px-4 py-8 sm:px-6">
          {choosesPlan && (
            <ChoosePlanCard
              // A new Terms version must be accepted afresh.
              key={data.termsVersion}
              data={data}
              notice={arrival.checkoutStatus === 'cancelled' ? CHECKOUT_CANCELLED : null}
            />
          )}
          <ProfileCard />
          <XAccountCard notice={arrival.xConnectionNotice ?? null} />
          {sells_plans && (
            <SubscriptionCard
              data={data}
              isLoading={billing.isLoading}
              loadError={billing.loadError}
            />
          )}
          <ApiKeysSection />
          <AppearanceCard />
          <footer className="pt-4">
            {/* A new tab, because leaving the signed-in layout would drop the Post on New post. */}
            <LegalLinks
              newTab
              listClassName="flex flex-wrap justify-center gap-x-5 gap-y-1 font-sans text-xs text-muted-foreground"
              linkClassName={LEGAL_LINK_CLASS}
            />
          </footer>
        </div>
      </div>
    </>
  );
}
