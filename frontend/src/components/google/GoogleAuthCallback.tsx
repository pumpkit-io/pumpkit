import { useEffect, useRef } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { session } from '@/lib/session';
import { track } from '@/lib/analytics';

export function GoogleAuthCallback() {
  const navigate = useNavigate();
  const { hash } = useLocation();
  const handled = useRef(false);

  useEffect(() => {
    if (handled.current) return;
    handled.current = true;
    // Replace, so the URL holding the access token leaves browser history.
    if (session.startFromFragment(hash)) {
      track('login_google_succeeded');
      navigate('/home', { replace: true });
    } else {
      track('login_google_failed', { error_code: 'sign_in_failed' });
      navigate('/login?error=sign_in_failed', { replace: true });
    }
  }, [hash, navigate]);

  return (
    <div className="flex justify-center items-center h-screen">
      <p>Processing Google login...</p>
    </div>
  );
}
