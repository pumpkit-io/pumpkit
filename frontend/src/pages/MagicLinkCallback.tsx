import { useSignInCallback } from '@/components/auth/useSignInCallback';
import { LoaderCircle } from 'lucide-react';
import { AuthShell } from './layout/AuthShell';
import { SIGN_IN_ERROR } from '@/lib/session';
import { track } from '@/lib/analytics';

export function MagicLinkCallback() {
  useSignInCallback({
    errorCodeFor: () => SIGN_IN_ERROR.invalidMagicLink,
    onSucceeded: () => track('login_magic_link_callback_succeeded'),
    onFailed: (errorCode) => track('login_magic_link_callback_failed', { error_code: errorCode }),
  });

  return (
    <AuthShell>
      <p
        role="status"
        className="flex items-center gap-2.5 font-sans text-sm text-muted-foreground"
      >
        <LoaderCircle
          aria-hidden
          className="h-4 w-4 animate-spin text-primary motion-reduce:animate-none"
        />
        Signing you in…
      </p>
    </AuthShell>
  );
}
