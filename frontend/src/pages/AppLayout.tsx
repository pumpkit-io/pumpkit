import { Outlet } from 'react-router-dom';
import { Toaster } from '@/components/Toaster';
import { BillingProvider } from '@/features/billing/BillingProvider';
import { SubscribedProvider } from '@/features/billing/SubscribedProvider';
import { InspirationAuthorsProvider } from '@/features/inspirationAuthors/InspirationAuthorsProvider';
import { PostCountsProvider } from '@/features/posts/PostCountsProvider';
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
          <PostCountsProvider>
            <Shell
              banner={<ReconnectXBanner />}
              sidebar={<Sidebar />}
              sidebarDrawer={<SidebarMobileDrawer />}
              main={<Outlet />}
            />
            <Toaster />
          </PostCountsProvider>
        </InspirationAuthorsProvider>
      </XConnectionProvider>
    </ProfileProvider>
  );
}

/**
 * The signed-in shell around every page in `signedInRoutes`. The Persona lives here, for the
 * sidebar's count, the Persona chip and the Persona page, and so do the Post counts, for the
 * sidebar's Failed badge and the Posts tabs. Each Post is read by its own page.
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
