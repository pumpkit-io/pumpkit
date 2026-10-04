import { useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';

export function MagicLinkCallback() {
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

    if (accessToken && expiresAt) {
      auth.login(accessToken, expiresAt);
      navigate('/home');
    } else {
      navigate('/login?error=invalid_magic_link');
    }
  }, [hash, auth, navigate]);

  return (
    <div className="flex justify-center items-center h-screen bg-[#18181B] text-slate-100">
      <p>Signing you in...</p>
    </div>
  );
}
