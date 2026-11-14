import { useState, useEffect } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { Button } from '../components/ui/button';
import { CTA_CLASSES } from '@/components/blocks/cta-classes';
import { cn } from '@/lib/utils';
import { CompanyFooter } from '@/features/legal/CompanyFooter';
import { useInstance } from '@/features/instance/useInstance';
import { PRIVACY_PATH, TERMS_PATH } from '@/features/legal/documents';
import { TEXT_LINK_CLASS } from '@/features/legal/textLink';
import { xSignInService } from '@/services/xSignInService';
import { redirectTo } from '@/lib/navigation';
import { track } from '../lib/analytics';
import mascot from '@/assets/brand/mascot.svg';
import mascotHopWave from '@/assets/brand/mascot-hop-wave.gif';
import { isSignInErrorCode, SIGN_IN_ERROR, type SignInErrorCode } from '../lib/session';

const SIGN_IN_ERROR_MESSAGES: Record<SignInErrorCode, string> = {
  [SIGN_IN_ERROR.invalidMagicLink]: 'That sign-in link is no longer available. Continue with X.',
  [SIGN_IN_ERROR.accountSuspended]: 'Your account has been suspended, so you cannot sign in.',
  [SIGN_IN_ERROR.signInFailed]: "We couldn't sign you in. Try again.",
  [SIGN_IN_ERROR.xEmailRequired]: 'Confirm an email address on X, then try signing in again.',
  [SIGN_IN_ERROR.xAuthorizationInvalid]:
    'This X authorization expired or is invalid. Continue with X again.',
  [SIGN_IN_ERROR.xAuthorizationCancelled]:
    'You cancelled X authorization. Continue with X when you are ready.',
  [SIGN_IN_ERROR.xPermissionsRequired]:
    'Allow all requested X permissions so Pumpkit can sign you in and publish your posts.',
  [SIGN_IN_ERROR.xAccountUnavailable]: 'This X account cannot sign in right now. Contact support.',
  [SIGN_IN_ERROR.xProviderFailed]: 'X is not answering right now. Try signing in again shortly.',
  [SIGN_IN_ERROR.emailNotAllowed]: "This site doesn't accept sign-ins from that email address.",
};

export function Login() {
  const location = useLocation();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { operator, app_name } = useInstance();
  const hasTerms = operator !== null;

  useEffect(() => {
    const code = new URLSearchParams(location.search).get('error');
    if (!isSignInErrorCode(code)) return;
    setError(SIGN_IN_ERROR_MESSAGES[code]);
    // Drop the code from the URL so a reload doesn't show the message again.
    window.history.replaceState({}, document.title, location.pathname);
  }, [location.search, location.pathname]);

  const continueWithX = async () => {
    setLoading(true);
    setError(null);
    track('login_x_clicked');
    try {
      redirectTo(await xSignInService.start());
    } catch {
      setError("Couldn't open X. Try again.");
      setLoading(false);
    }
  };

  return (
    <div className="login grid min-h-screen bg-background text-foreground lg:grid-cols-2">
      <div className="flex flex-col">
        <main className="flex flex-1 items-center justify-center px-4 py-12">
          <div className="w-full max-w-[440px]">
            <div className="rounded-2xl border border-border bg-card p-8 shadow-raised sm:p-10">
              <img src={mascot} alt="" className="h-10 w-auto select-none" draggable={false} />
              <h1 className="mt-6 text-3xl font-normal leading-tight tracking-tight text-foreground">
                Welcome to {app_name}
              </h1>
              <p className="mt-3 text-base leading-relaxed text-muted-foreground">
                Write X posts that fit who you are and who you write for.
              </p>

              <div className="mt-8 grid gap-6">
                <p className="text-sm leading-relaxed text-muted-foreground">
                  Continuing with X signs you in and authorizes {app_name} to publish your posts,
                  including media and scheduled posts.
                </p>
                {error && (
                  <div
                    role="alert"
                    className="rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-sm font-medium text-destructive"
                  >
                    {error}
                  </div>
                )}
                <Button
                  variant="solid"
                  className={cn(CTA_CLASSES, 'h-11 w-full')}
                  disabled={loading}
                  aria-busy={loading}
                  onClick={() => void continueWithX()}
                >
                  {loading ? 'Opening X…' : 'Continue with X'}
                </Button>
              </div>
            </div>
            {/* Informational only: Users accept the Terms at checkout (ADR 0010). */}
            {hasTerms && (
              <p className="mt-6 text-center text-xs leading-5 text-muted-foreground">
                By continuing, you agree to the{' '}
                <Link to={TERMS_PATH} className={TEXT_LINK_CLASS}>
                  Terms
                </Link>{' '}
                and acknowledge the{' '}
                <Link to={PRIVACY_PATH} className={TEXT_LINK_CLASS}>
                  Privacy Policy
                </Link>
                .
              </p>
            )}
          </div>
        </main>
        <CompanyFooter />
      </div>
      <aside className="hidden items-center justify-center border-l border-border bg-muted lg:flex">
        <picture>
          <source srcSet={mascot} media="(prefers-reduced-motion: reduce)" />
          <img
            src={mascotHopWave}
            alt=""
            className="w-72 select-none [image-rendering:pixelated]"
            draggable={false}
          />
        </picture>
      </aside>
    </div>
  );
}
