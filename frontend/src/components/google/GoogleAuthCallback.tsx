import { useSignInCallback } from '@/components/auth/useSignInCallback';
import { SIGN_IN_ERROR } from '@/lib/session';
import { track } from '@/lib/analytics';

export function GoogleAuthCallback() {
  useSignInCallback({
    errorCodeFor: () => SIGN_IN_ERROR.signInFailed,
    onSucceeded: () => track('login_google_succeeded'),
    onFailed: (errorCode) => track('login_google_failed', { error_code: errorCode }),
  });

  return (
    <div className="flex justify-center items-center h-screen">
      <p>Processing Google login...</p>
    </div>
  );
}
