import { useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../../contexts/AuthContext';
import { track } from '../../lib/analytics';

export function GoogleAuthCallback() {
  const navigate = useNavigate();
  const auth = useAuth();
  const hash = window.location.hash;
  const handled = useRef(false);

  useEffect(() => {
    if (handled.current) return;
    handled.current = true;
    const params = new URLSearchParams(hash.substring(1));
    const accessToken = params.get('access_token');
    const expiresAt = params.get('expires_at');

    if (accessToken) {
      track('login_google_succeeded');
      auth.login(accessToken, expiresAt ?? undefined);
      navigate('/home');
    } else {
      track('login_google_failed', { error_code: 'google_token_missing' });
      navigate('/login?error=google_token_missing');
    }
  }, [hash, auth, navigate]);

  return (
    <div className="flex justify-center items-center h-screen">
      <p>Processing Google login...</p>
    </div>
  );
}
