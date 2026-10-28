import { Outlet } from 'react-router-dom';
import { BillingProvider } from '@/features/billing/BillingProvider';
import { SubscribedProvider } from '@/features/billing/SubscribedProvider';
import { InspirationAuthorsProvider } from '@/features/inspirationAuthors/InspirationAuthorsProvider';
import { Sidebar } from '@/features/sidebar/Sidebar';
import { SidebarMobileDrawer } from '@/features/sidebar/SidebarMobileDrawer';
import { SidebarProvider } from '@/features/sidebar/SidebarProvider';
import { ReconnectXBanner } from '@/features/xConnection/ReconnectXBanner';
import { XConnectionProvider } from '@/features/xConnection/XConnectionProvider';
import { ProfileProvider } from './layout/ProfileContext';
import { Shell } from './layout/Shell';
import { useBootstrap } from './layout/useBootstrap';

function AppLayoutInner() {
  const { profile, setProfile } = useBootstrap();

  return (
    <ProfileProvider value={profile} setValue={setProfile}>
      <XConnectionProvider>
        <InspirationAuthorsProvider>
          <Shell
            banner={<ReconnectXBanner />}
            sidebar={<Sidebar />}
            sidebarDrawer={<SidebarMobileDrawer />}
            main={<Outlet />}
          />
        </InspirationAuthorsProvider>
      </XConnectionProvider>
    </ProfileProvider>
  );
}

/**
 * The signed-in shell around every page in `signedInRoutes`. The Persona lives here, for the
 * sidebar's count, the Persona chip and the Persona page; each Post is read by its own page.
 */
export function AppLayout() {
  return (
    <SidebarProvider>
      <BillingProvider>
        <SubscribedProvider>
          <AppLayoutInner />
        </SubscribedProvider>
      </BillingProvider>
    </SidebarProvider>
  );
}
