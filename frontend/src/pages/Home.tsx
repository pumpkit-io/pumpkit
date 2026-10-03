import { useEffect, useRef } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { AccountDialog } from '@/features/account/AccountDialog';
import { AccountProvider } from '@/features/account/AccountProvider';
import { BillingDialog } from '@/features/billing/BillingDialog';
import { BillingProvider } from '@/features/billing/BillingProvider';
import { useBilling } from '@/features/billing/useBilling';
import { Sidebar } from '@/features/sidebar/Sidebar';
import { SidebarMobileDrawer } from '@/features/sidebar/SidebarMobileDrawer';
import { SidebarProvider } from '@/features/sidebar/SidebarProvider';
import { Topbar } from '@/features/topbar/Topbar';
import { track } from '@/lib/analytics';
import { APP_NAME } from '@/lib/app';
import { fireSuccessConfetti } from '@/lib/confetti';
import { ProfileProvider } from './Home/ProfileContext';
import { Shell } from './Home/Shell';
import { useBootstrap } from './Home/useBootstrap';

interface HomeLocationState {
  checkoutStatus?: 'success' | 'cancelled';
  checkoutKind?: string;
  openBilling?: boolean;
}

/** Opens the billing dialog when arriving from Stripe or /billing. */
function useBillingReturn() {
  const location = useLocation();
  const navigate = useNavigate();
  const billing = useBilling();
  const consumedRef = useRef(false);

  useEffect(() => {
    if (consumedRef.current) return;
    const state = (location.state ?? {}) as HomeLocationState;
    if (!state.checkoutStatus && !state.openBilling) return;
    consumedRef.current = true;
    navigate('.', { replace: true, state: null });

    if (state.checkoutStatus === 'success') {
      track('billing_checkout_succeeded', { kind: state.checkoutKind });
      fireSuccessConfetti(null);
      billing.open('checkout_success');
    } else if (state.checkoutStatus === 'cancelled') {
      track('billing_checkout_cancelled', { kind: state.checkoutKind });
      billing.openWithError('Checkout was cancelled. You have not been charged.', 'checkout_cancelled');
    } else {
      billing.open('billing_route');
    }
  }, [location.state, navigate, billing]);
}

function HomeInner() {
  const { profile, setProfile } = useBootstrap();
  useBillingReturn();
  const firstName = profile?.firstName?.trim();

  return (
    <ProfileProvider value={profile} setValue={setProfile}>
      <Shell
        sidebar={<Sidebar />}
        sidebarDrawer={<SidebarMobileDrawer />}
        main={
          <>
            <Topbar title="Home" />
            <div className="flex flex-1 items-center justify-center px-6">
              <div className="max-w-md text-center">
                <h1 className="text-3xl font-normal tracking-tight text-foreground">
                  Welcome{firstName ? `, ${firstName}` : ''}
                </h1>
                <p className="mt-3 font-sans text-sm text-muted-foreground">
                  This is the {APP_NAME} app shell. Build your product here — see “Building your app” in the README.
                </p>
              </div>
            </div>
          </>
        }
      />
      <AccountDialog />
      <BillingDialog />
    </ProfileProvider>
  );
}

export function Home() {
  return (
    <SidebarProvider>
      <BillingProvider>
        <AccountProvider>
          <HomeInner />
        </AccountProvider>
      </BillingProvider>
    </SidebarProvider>
  );
}
