import { Outlet } from 'react-router-dom';
import { AccountDialog } from '@/features/account/AccountDialog';
import { AccountProvider } from '@/features/account/AccountProvider';
import { BillingDialog } from '@/features/billing/BillingDialog';
import { BillingProvider } from '@/features/billing/BillingProvider';
import { SubscribedProvider } from '@/features/billing/SubscribedProvider';
import { InspirationAuthorsProvider } from '@/features/inspirationAuthors/InspirationAuthorsProvider';
import { PostWriterProvider } from '@/features/posts/PostWriterProvider';
import { Sidebar } from '@/features/sidebar/Sidebar';
import { SidebarMobileDrawer } from '@/features/sidebar/SidebarMobileDrawer';
import { SidebarProvider } from '@/features/sidebar/SidebarProvider';
import { useInstance } from '@/features/instance/useInstance';
import { XConnectionProvider } from '@/features/xConnection/XConnectionProvider';
import { ProfileProvider } from './layout/ProfileContext';
import { Shell } from './layout/Shell';
import { useBootstrap } from './layout/useBootstrap';

function AppLayoutInner() {
  const { profile, setProfile } = useBootstrap();
  const { sells_plans } = useInstance();

  return (
    <ProfileProvider value={profile} setValue={setProfile}>
      <XConnectionProvider>
        <InspirationAuthorsProvider>
          <PostWriterProvider>
            <Shell
              sidebar={<Sidebar />}
              sidebarDrawer={<SidebarMobileDrawer />}
              main={<Outlet />}
            />
          </PostWriterProvider>
        </InspirationAuthorsProvider>
      </XConnectionProvider>
      <AccountDialog />
      {sells_plans && <BillingDialog />}
    </ProfileProvider>
  );
}

/**
 * The signed-in shell around every page in `signedInRoutes`. The Post lives in its
 * PostWriterProvider, so it stays on /new while the User visits another page and comes back.
 * The Persona lives here too, for the sidebar's count, the Persona chip and the Persona page.
 */
export function AppLayout() {
  return (
    <SidebarProvider>
      <BillingProvider>
        <SubscribedProvider>
          <AccountProvider>
            <AppLayoutInner />
          </AccountProvider>
        </SubscribedProvider>
      </BillingProvider>
    </SidebarProvider>
  );
}
