import { Outlet } from 'react-router-dom';
import { AccountDialog } from '@/features/account/AccountDialog';
import { AccountProvider } from '@/features/account/AccountProvider';
import { BillingDialog } from '@/features/billing/BillingDialog';
import { BillingProvider } from '@/features/billing/BillingProvider';
import { SubscribedProvider } from '@/features/billing/SubscribedProvider';
import { PostWriterProvider } from '@/features/posts/PostWriterProvider';
import { Sidebar } from '@/features/sidebar/Sidebar';
import { SidebarMobileDrawer } from '@/features/sidebar/SidebarMobileDrawer';
import { SidebarProvider } from '@/features/sidebar/SidebarProvider';
import { XConnectionProvider } from '@/features/xConnection/XConnectionProvider';
import { ProfileProvider } from './Home/ProfileContext';
import { Shell } from './Home/Shell';
import { useBootstrap } from './Home/useBootstrap';

function AppLayoutInner() {
  const { profile, setProfile } = useBootstrap();

  return (
    <ProfileProvider value={profile} setValue={setProfile}>
      <XConnectionProvider>
        <PostWriterProvider>
          <Shell sidebar={<Sidebar />} sidebarDrawer={<SidebarMobileDrawer />} main={<Outlet />} />
        </PostWriterProvider>
      </XConnectionProvider>
      <AccountDialog />
      <BillingDialog />
    </ProfileProvider>
  );
}

/**
 * The signed-in shell shared by Home and Scheduled. The Post lives in its PostWriterProvider,
 * so it stays on screen while the User visits another page and comes back. Home posts Finals
 * through the same X connection that Scheduled manages.
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
