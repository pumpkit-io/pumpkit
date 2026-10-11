import { useSignInCallback } from '@/components/auth/useSignInCallback';
import { CompanyFooter } from '@/features/legal/CompanyFooter';
import { SIGN_IN_ERROR } from '@/lib/session';
import { track } from '@/lib/analytics';

export function MagicLinkCallback() {
  useSignInCallback({
    errorCodeFor: () => SIGN_IN_ERROR.invalidMagicLink,
    onSucceeded: () => track('login_magic_link_callback_succeeded'),
    onFailed: (errorCode) => track('login_magic_link_callback_failed', { error_code: errorCode }),
  });

  return (
    <div className="flex min-h-screen flex-col bg-background text-foreground">
      <main className="flex flex-1 items-center justify-center">
        <p role="status">Signing you in…</p>
      </main>
      <CompanyFooter />
    </div>
  );
}
