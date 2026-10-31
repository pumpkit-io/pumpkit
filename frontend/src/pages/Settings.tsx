import { useEffect, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { useAuth } from '@/contexts/AuthContext';
import { ProfileCard } from '@/features/account/ProfileCard';
import { ApiKeysSection } from '@/features/apiKeys/ApiKeysSection';
import { SubscriptionCard } from '@/features/billing/SubscriptionCard';
import { useBilling } from '@/features/billing/useBilling';
import { useInstance } from '@/features/instance/useInstance';
import { LegalLinks } from '@/features/legal/LegalLinks';
import { AppearanceCard } from '@/features/theme/AppearanceCard';
import { Topbar } from '@/features/topbar/Topbar';
import { XAccountCard } from '@/features/xConnection/XAccountCard';
import { XPhotoOfferDialog } from '@/features/xConnection/XPhotoOfferDialog';
import { track } from '@/lib/analytics';

/** What the X callback leaves in the location state for Settings. */
export interface SettingsLocationState {
  xConnectionNotice?: string;
}

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
    if (arrival.state.xConnectionNotice) {
      navigate({ hash: arrival.hash }, { replace: true, state: null });
    }
  }, [arrival, navigate]);

  return arrival.state;
}

/** Loads billing on every visit, since Stripe changes it outside the app. */
function useBillingOnArrival() {
  const { sells_plans } = useInstance();
  const { load } = useBilling();

  useEffect(() => {
    if (sells_plans) void load();
  }, [sells_plans, load]);
}

/** Rendered inside AppLayout: the User's account as one column of cards. */
export function Settings() {
  const { logout } = useAuth();
  const { sells_plans, x_connection } = useInstance();
  const billing = useBilling();
  const arrival = useArrivalState();
  useBillingOnArrival();

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
          <ProfileCard />
          {x_connection && (
            <>
              <XAccountCard notice={arrival.xConnectionNotice ?? null} />
              <XPhotoOfferDialog />
            </>
          )}
          {sells_plans && (
            <SubscriptionCard
              data={billing.data}
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
