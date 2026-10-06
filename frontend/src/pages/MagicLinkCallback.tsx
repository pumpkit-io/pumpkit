import { useSignInCallback } from '@/components/auth/useSignInCallback';
import { SIGN_IN_ERROR } from '@/lib/session';
import { track } from '@/lib/analytics';

export function MagicLinkCallback() {
  useSignInCallback({
    errorCodeFor: () => SIGN_IN_ERROR.invalidMagicLink,
    onSucceeded: () => track('login_magic_link_callback_succeeded'),
    onFailed: (errorCode) => track('login_magic_link_callback_failed', { error_code: errorCode }),
  });

  return (
    <div className="flex h-screen items-center justify-center bg-background text-foreground">
      <p role="status">Signing you in…</p>
    </div>
  );
}
