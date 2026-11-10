import { Navigate, useLocation } from 'react-router-dom';
import { ProtectedRoute } from '@/components/auth/ProtectedRoute';
import { signInPath, SIGN_IN_ERROR } from '@/lib/session';
import { XSignInCallback } from './XSignInCallback';
import { XConnectionCallback } from './XConnectionCallback';

export function XOAuthCallback() {
  const { search } = useLocation();
  const state = new URLSearchParams(search).get('state');
  // The prefix selects a handler; only its server-side attempt can authorize the result.
  if (state?.startsWith('signin.')) return <XSignInCallback />;
  if (state?.startsWith('reconnect.'))
    return (
      <ProtectedRoute>
        <XConnectionCallback />
      </ProtectedRoute>
    );
  return <Navigate to={signInPath(SIGN_IN_ERROR.xAuthorizationInvalid)} replace />;
}
