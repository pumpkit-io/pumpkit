import { useEffect, useRef } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { session, signInPath, SIGN_IN_ERROR, isSignInErrorCode } from '@/lib/session';
import { returnTo } from '@/lib/returnTo';
import { errorMessage } from '@/services/apiErrors';
import { xSignInService } from '@/services/xSignInService';

export function XSignInCallback() {
  const { search } = useLocation();
  const navigate = useNavigate();
  const handled = useRef(false);

  useEffect(() => {
    if (handled.current) return;
    handled.current = true;
    const params = new URLSearchParams(search);
    window.history.replaceState({}, document.title, window.location.pathname);
    const state = params.get('state');
    if (!state) {
      navigate(signInPath(SIGN_IN_ERROR.xAuthorizationInvalid), { replace: true });
      return;
    }
    xSignInService
      .complete({ state, code: params.get('code'), error: params.get('error') })
      .then(({ accessToken, expiresAt }) => {
        const result = session.startFromCredentials(accessToken, expiresAt);
        navigate(result.ok ? (returnTo.take() ?? '/new') : signInPath(SIGN_IN_ERROR.signInFailed), {
          replace: true,
        });
      })
      .catch((error: unknown) => {
        const detail = errorMessage(error, '');
        navigate(signInPath(isSignInErrorCode(detail) ? detail : SIGN_IN_ERROR.xProviderFailed), {
          replace: true,
        });
      });
  }, [search, navigate]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-background text-foreground">
      <p role="status" className="text-sm text-muted-foreground">
        Signing you in with X…
      </p>
    </div>
  );
}
