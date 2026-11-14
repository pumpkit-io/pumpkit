import { Outlet } from 'react-router-dom';
import { Toaster } from '@/components/Toaster';
import { BillingProvider } from '@/features/billing/BillingProvider';
import { SubscribedProvider } from '@/features/billing/SubscribedProvider';
import { PostCountsProvider } from '@/features/posts/PostCountsProvider';
import { Sidebar } from '@/features/sidebar/Sidebar';
import { SidebarMobileDrawer } from '@/features/sidebar/SidebarMobileDrawer';
import { SidebarProvider } from '@/features/sidebar/SidebarProvider';
import { ReconnectXBanner } from '@/features/xConnection/ReconnectXBanner';
import { XConnectionProvider } from '@/features/xConnection/XConnectionProvider';
import { ConfirmLeavingNavigation } from '@/lib/ConfirmLeavingNavigation';
import { ProfileProvider } from './layout/ProfileContext';
import { Shell } from './layout/Shell';
import { useBootstrap } from './layout/useBootstrap';

function AppLayoutInner() {
  const { profile, setProfile } = useBootstrap();

  return (
    <ProfileProvider value={profile} setValue={setProfile}>
      <XConnectionProvider>
        <PostCountsProvider>
          <Shell
            banner={<ReconnectXBanner />}
            sidebar={<Sidebar />}
            sidebarDrawer={<SidebarMobileDrawer />}
            main={<Outlet />}
          />
          <Toaster />
        </PostCountsProvider>
      </XConnectionProvider>
    </ProfileProvider>
  );
}

/**
 * The signed-in shell around every page in `signedInRoutes`. The Post counts live here, for the
 * sidebar's Failed badge and the Posts tabs. Each Post is read by its own page.
 */
export function AppLayout() {
  return (
    <ConfirmLeavingNavigation>
      <SidebarProvider>
        <BillingProvider>
          <SubscribedProvider>
            <AppLayoutInner />
          </SubscribedProvider>
        </BillingProvider>
      </SidebarProvider>
    </ConfirmLeavingNavigation>
  );
}
