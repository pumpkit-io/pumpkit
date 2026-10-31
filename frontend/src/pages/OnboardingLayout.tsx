import { Outlet } from 'react-router-dom';
import { Brand } from '@/components/brand/Brand';
import { LegalLinks } from '@/features/legal/LegalLinks';
import { AccountMenu } from '@/features/onboarding/AccountMenu';
import { StepIndicator } from '@/features/onboarding/StepIndicator';
import { useOnboarding } from '@/features/onboarding/useOnboarding';
import { useBootstrap } from './layout/useBootstrap';

const FOOTER_LINK_CLASS =
  'rounded-sm underline-offset-4 transition-colors hover:text-foreground hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring';

/**
 * The focused shell of the Paywall: no sidebar, the steps before Pumpkit opens, the account
 * menu and the legal links. Content sits left-aligned in one column on the raised panel.
 */
export function OnboardingLayout() {
  const { state } = useOnboarding();
  const { profile } = useBootstrap();
  const current = state.status === 'ready' ? state.nextStep : null;

  return (
    <div className="flex min-h-[100dvh] flex-col bg-background text-foreground">
      <header className="flex items-center justify-between gap-4 px-4 py-3 sm:px-6">
        <Brand size="sm" showName />
        {current && <StepIndicator current={current} />}
        <AccountMenu profile={profile} />
      </header>
      <main className="flex-1 bg-card px-4 py-8 sm:mx-2 sm:rounded-xl sm:border sm:border-border sm:px-6 sm:py-14 sm:shadow-panel">
        <div className="mx-auto w-full max-w-[720px]">
          <Outlet />
        </div>
      </main>
      <footer className="px-4 py-5 sm:px-6">
        {/* A new tab, so ticked Terms boxes survive reading the Terms. */}
        <LegalLinks
          newTab
          listClassName="flex flex-wrap gap-x-5 gap-y-1 font-sans text-xs text-muted-foreground"
          linkClassName={FOOTER_LINK_CLASS}
        />
      </footer>
    </div>
  );
}
