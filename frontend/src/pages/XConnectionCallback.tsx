import { useEffect, useRef } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { track } from '@/lib/analytics';
import { errorMessage } from '@/services/apiErrors';
import { xConnectionService } from '@/services/xConnectionService';
import type { ScheduledLocationState } from './Scheduled';

/**
 * Where X's consent screen sends the browser back. Completes the authorization with the
 * query's code and state, then returns to Scheduled with a message, replacing this entry.
 */
export function XConnectionCallback() {
  const navigate = useNavigate();
  const { search } = useLocation();
  // StrictMode runs effects twice in development, and a state works only once.
  const handled = useRef(false);

  useEffect(() => {
    if (handled.current) return;
    handled.current = true;

    const back = (xConnectionNotice: string) => {
      const state: ScheduledLocationState = { xConnectionNotice };
      navigate('/scheduled', { replace: true, state });
    };
    const params = new URLSearchParams(search);
    const code = params.get('code');
    const state = params.get('state');
    if (params.get('error')) {
      back('You cancelled connecting X. Connect it again whenever you like.');
      return;
    }
    if (!code || !state) {
      back("X didn't finish connecting your account. Please try again.");
      return;
    }
    xConnectionService
      .complete(code, state)
      .then((connection) => {
        track('x_connected');
        back(`Connected @${connection.handle}.`);
      })
      .catch((e) => back(errorMessage(e, "Couldn't connect X. Please try again.")));
  }, [search, navigate]);

  return (
    <div className="flex h-screen items-center justify-center bg-background text-foreground">
      <p role="status">Connecting your X account…</p>
    </div>
  );
}
