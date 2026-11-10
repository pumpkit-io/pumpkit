import { useEffect, useRef } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useOnboarding } from '@/features/onboarding/useOnboarding';
import { xConnectionReturn } from '@/features/xConnection/xConnectionReturn';
import { track } from '@/lib/analytics';
import { errorMessage } from '@/services/apiErrors';
import { xConnectionService } from '@/services/xConnectionService';

export function XConnectionCallback() {
  const navigate = useNavigate();
  const { refresh } = useOnboarding();
  const { search } = useLocation();
  const handled = useRef(false);

  useEffect(() => {
    if (handled.current) return;
    handled.current = true;
    const params = new URLSearchParams(search);
    window.history.replaceState({}, document.title, window.location.pathname);
    const back = async (notice: string, failed = false) => {
      const destination = xConnectionReturn.take() ?? '/settings';
      const step = await refresh();
      navigate(step === 'paywall' ? '/subscribe' : destination, {
        replace: true,
        state: { xConnectionNotice: notice, xConnectionFailed: failed },
      });
    };
    if (params.get('error')) {
      void back('You cancelled reconnecting X. Try again when you are ready.', true);
      return;
    }
    const code = params.get('code');
    const state = params.get('state');
    if (!code || !state) {
      void back("X didn't finish reconnecting your account. Try again.", true);
      return;
    }
    xConnectionService
      .complete(code, state)
      .then((connection) => {
        track('x_connected');
        return back(`Reconnected @${connection.handle}.`);
      })
      .catch((error: unknown) =>
        back(errorMessage(error, "Couldn't reconnect X. Try again."), true),
      );
  }, [search, navigate, refresh]);

  return (
    <div className="flex h-screen items-center justify-center bg-background text-foreground">
      <p role="status">Reconnecting X…</p>
    </div>
  );
}
