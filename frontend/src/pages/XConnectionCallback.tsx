import { useEffect, useRef } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import {
  ONBOARDING_PATH,
  PAYWALL_PATH,
  type OnboardingLocationState,
  type XConnectionArrival,
} from '@/features/onboarding/paths';
import { useOnboarding } from '@/features/onboarding/useOnboarding';
import {
  xConnectionReturn,
  type XConnectionNoticeState,
} from '@/features/xConnection/xConnectionReturn';
import { track } from '@/lib/analytics';
import { errorCode, errorMessage, errorStatus } from '@/services/apiErrors';
import { xConnectionService } from '@/services/xConnectionService';

/**
 * Where X's consent screen sends the browser back. Completes the authorization with the
 * query's code and state, then returns to the X step while Onboarding isn't finished, and
 * otherwise with a message to the Post page that sent the User to X, or to Settings, replacing
 * this entry.
 */
export function XConnectionCallback() {
  const navigate = useNavigate();
  const { search } = useLocation();
  const { refresh } = useOnboarding();
  // StrictMode runs effects twice in development, and a state works only once.
  const handled = useRef(false);

  useEffect(() => {
    if (handled.current) return;
    handled.current = true;

    const back = async (arrival: XConnectionArrival, xConnectionNotice: string) => {
      const returnPath = xConnectionReturn.take();
      // A failed check lands on the saved Post or Settings, whose gate sends the User on if
      // Onboarding isn't done.
      const nextStep = await refresh();
      if (nextStep == null || nextStep === 'paywall') {
        const state: XConnectionNoticeState = { xConnectionNotice };
        navigate(nextStep === 'paywall' ? PAYWALL_PATH : (returnPath ?? '/settings'), {
          replace: true,
          state,
        });
      } else {
        const state: OnboardingLocationState = { xConnection: arrival };
        navigate(ONBOARDING_PATH, { replace: true, state });
      }
    };
    const fail = (reason: string) => back({ outcome: 'failed', reason }, reason);

    const params = new URLSearchParams(search);
    const code = params.get('code');
    const state = params.get('state');
    if (params.get('error')) {
      void back(
        {
          outcome: 'failed',
          reason: "You cancelled connecting X. Connect it whenever you're ready.",
        },
        'You cancelled connecting X. Connect it again whenever you like.',
      );
      return;
    }
    if (!code || !state) {
      void fail("X didn't finish connecting your account. Try again.");
      return;
    }
    xConnectionService
      .complete(code, state)
      .then((connection) => {
        track('x_connected');
        const { handle, photoUrl } = connection;
        return back({ outcome: 'connected', handle, photoUrl }, `Connected @${handle}.`);
      })
      .catch((e) => {
        const reason = errorMessage(e, "Couldn't connect X. Try again.");
        return errorStatus(e) === 409 && errorCode(e) !== 'X_ACCOUNT_MISMATCH'
          ? back({ outcome: 'taken' }, reason)
          : fail(reason);
      });
  }, [search, navigate, refresh]);

  return (
    <div className="flex h-screen items-center justify-center bg-background text-foreground">
      <p role="status">Connecting your X account…</p>
    </div>
  );
}
