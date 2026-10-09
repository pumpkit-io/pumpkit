import { useEffect, useRef } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { AccountDialog } from '@/features/account/AccountDialog';
import { AccountProvider } from '@/features/account/AccountProvider';
import { BillingDialog } from '@/features/billing/BillingDialog';
import { BillingProvider } from '@/features/billing/BillingProvider';
import { SubscribedProvider } from '@/features/billing/SubscribedProvider';
import { useBilling } from '@/features/billing/useBilling';
import { Sidebar } from '@/features/sidebar/Sidebar';
import { SidebarMobileDrawer } from '@/features/sidebar/SidebarMobileDrawer';
import { SidebarProvider } from '@/features/sidebar/SidebarProvider';
import { InspirationAuthorsPanel } from '@/features/inspirationAuthors/InspirationAuthorsPanel';
import { InspirationAuthorsProvider } from '@/features/inspirationAuthors/InspirationAuthorsProvider';
import { PostWriter } from '@/features/posts/PostWriter';
import { PostWriterProvider } from '@/features/posts/PostWriterProvider';
import { Topbar } from '@/features/topbar/Topbar';
import { track } from '@/lib/analytics';
import { fireSuccessConfetti } from '@/lib/confetti';
import { ProfileProvider } from './Home/ProfileContext';
import { Shell } from './Home/Shell';
import { useBootstrap } from './Home/useBootstrap';

interface HomeLocationState {
  checkoutStatus?: 'success' | 'cancelled';
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
      track('billing_checkout_succeeded');
      fireSuccessConfetti(null);
      billing.open('checkout_success');
    } else if (state.checkoutStatus === 'cancelled') {
      track('billing_checkout_cancelled');
      billing.openWithError(
        'Checkout was cancelled. You have not been charged.',
        'checkout_cancelled',
      );
    } else {
      billing.open('billing_route');
    }
  }, [location.state, navigate, billing]);
}

function HomeInner() {
  const { profile, setProfile } = useBootstrap();
  useBillingReturn();

  return (
    <ProfileProvider value={profile} setValue={setProfile}>
      <PostWriterProvider>
        <Shell
          sidebar={<Sidebar />}
          sidebarDrawer={<SidebarMobileDrawer />}
          main={
            <>
              <Topbar title="Home" />
              <div className="flex-1 overflow-y-auto">
                <div className="mx-auto w-full max-w-2xl space-y-10 px-4 py-8 sm:px-6">
                  <InspirationAuthorsProvider>
                    <InspirationAuthorsPanel />
                    <PostWriter />
                  </InspirationAuthorsProvider>
                </div>
              </div>
            </>
          }
        />
      </PostWriterProvider>
      <AccountDialog />
      <BillingDialog />
    </ProfileProvider>
  );
}

export function Home() {
  return (
    <SidebarProvider>
      <BillingProvider>
        <SubscribedProvider>
          <AccountProvider>
            <HomeInner />
          </AccountProvider>
        </SubscribedProvider>
      </BillingProvider>
    </SidebarProvider>
  );
}
