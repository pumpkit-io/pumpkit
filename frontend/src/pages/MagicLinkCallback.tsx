import { useEffect, useRef } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { session } from '@/lib/session';
import { track } from '@/lib/analytics';

export function MagicLinkCallback() {
  const navigate = useNavigate();
  const { hash } = useLocation();
  const handled = useRef(false);

  useEffect(() => {
    if (handled.current) return;
    handled.current = true;
    // Replace, so the URL holding the access token leaves browser history.
    if (session.startFromFragment(hash)) {
      track('login_magic_link_callback_succeeded');
      navigate('/home', { replace: true });
    } else {
      track('login_magic_link_callback_failed', { error_code: 'invalid_magic_link' });
      navigate('/login?error=invalid_magic_link', { replace: true });
    }
  }, [hash, navigate]);

  return (
    <div className="flex justify-center items-center h-screen bg-[#18181B] text-slate-100">
      <p>Signing you in...</p>
    </div>
  );
}
