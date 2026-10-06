import { useEffect, useRef } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { session, signInPath, type SignInErrorCode, type StartFailureReason } from '@/lib/session';

interface SignInCallbackOptions {
  /** The sign-in page error code to show for a fragment that starts no Session. */
  errorCodeFor: (reason: StartFailureReason) => SignInErrorCode;
  /** Called once when the Session started. */
  onSucceeded: () => void;
  /** Called once with the error code when no Session started. */
  onFailed: (errorCode: SignInErrorCode) => void;
}

/**
 * Starts the Session from the URL fragment, then goes to home or to sign-in with an error.
 * Both navigations replace the entry so the access-token URL leaves browser history.
 */
export function useSignInCallback({ errorCodeFor, onSucceeded, onFailed }: SignInCallbackOptions) {
  const navigate = useNavigate();
  const { hash } = useLocation();
  // StrictMode runs effects twice in development; start the Session once.
  const handled = useRef(false);

  useEffect(() => {
    if (handled.current) return;
    handled.current = true;
    const result = session.startFromFragment(hash);
    if (result.ok) {
      onSucceeded();
      navigate('/home', { replace: true });
      return;
    }
    const errorCode = errorCodeFor(result.reason);
    onFailed(errorCode);
    navigate(signInPath(errorCode), { replace: true });
  }, [hash, navigate, errorCodeFor, onSucceeded, onFailed]);
}
