import type { ReactNode } from 'react';
import { useLocation } from 'react-router-dom';
import { Brand } from '@/components/brand/Brand';
import { LegalLinks } from '@/features/legal/LegalLinks';
import { AccountMenu } from '@/features/onboarding/AccountMenu';
import { ReconnectXBanner } from '@/features/xConnection/ReconnectXBanner';
import { XConnectionProvider } from '@/features/xConnection/XConnectionProvider';
import type { XConnectionNoticeState } from '@/features/xConnection/xConnectionReturn';
import { ProfileProvider } from './layout/ProfileContext';
import { useBootstrap } from './layout/useBootstrap';

const FOOTER_LINK_CLASS =
  'rounded-sm underline-offset-4 transition-colors hover:text-foreground hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring';

/**
 * The shell with no sidebar: the brand, an optional header item between it and the account menu,
 * and the legal links. The Paywall, Onboarding and the consent page render in it.
 */
export function FocusedLayout({ header, children }: { header?: ReactNode; children: ReactNode }) {
  const { profile, setProfile } = useBootstrap();
  const location = useLocation();
  const notice = (location.state as XConnectionNoticeState | null)?.xConnectionNotice ?? null;

  return (
    <ProfileProvider value={profile} setValue={setProfile}>
      <XConnectionProvider>
        <div className="flex min-h-[100dvh] flex-col bg-background text-foreground">
          <header className="flex flex-wrap items-center justify-between gap-x-4 gap-y-3 px-4 py-3 sm:px-6">
            <Brand size="sm" showName className="shrink-0" />
            {header && (
              <div className="order-last w-full min-w-0 sm:order-none sm:w-auto sm:flex-1">
                {header}
              </div>
            )}
            <div className="ml-auto shrink-0">
              <AccountMenu profile={profile} />
            </div>
          </header>
          <ReconnectXBanner notice={notice} />
          <main className="flex-1 bg-card px-4 py-8 sm:mx-2 sm:rounded-xl sm:border sm:border-border sm:px-6 sm:py-14 sm:shadow-panel">
            <div className="mx-auto w-full max-w-[720px]">{children}</div>
          </main>
          <footer className="px-4 py-5 sm:px-6">
            {/* A new tab, so ticked Terms boxes and a pending connection survive reading them. */}
            <LegalLinks
              newTab
              listClassName="flex flex-wrap gap-x-5 gap-y-1 font-sans text-xs text-muted-foreground"
              linkClassName={FOOTER_LINK_CLASS}
            />
          </footer>
        </div>
      </XConnectionProvider>
    </ProfileProvider>
  );
}
