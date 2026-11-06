import { useState, useEffect } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { Button } from '../components/ui/button';
import { GoogleAuthButton } from '../components/google/GoogleAuthButton';
import { CompanyFooter } from '@/features/legal/CompanyFooter';
import { useInstance } from '@/features/instance/useInstance';
import { PRIVACY_PATH, TERMS_PATH } from '@/features/legal/documents';
import { TEXT_LINK_CLASS } from '@/features/legal/textLink';
import { authService } from '../services/authService';
import { errorMessage, errorStatus } from '../services/apiErrors';
import { track } from '../lib/analytics';
import mascot from '@/assets/brand/mascot.svg';
import mascotHopWave from '@/assets/brand/mascot-hop-wave.gif';
import { isSignInErrorCode, SIGN_IN_ERROR, type SignInErrorCode } from '../lib/session';

function emailDomain(email: string): string {
  const at = email.lastIndexOf('@');
  return at >= 0 ? email.slice(at + 1).toLowerCase() : 'unknown';
}

const SIGN_IN_ERROR_MESSAGES: Record<SignInErrorCode, string> = {
  [SIGN_IN_ERROR.invalidMagicLink]:
    'That magic link is invalid or has expired. Request a new one below.',
  [SIGN_IN_ERROR.accountSuspended]: 'Your account has been suspended, so you cannot sign in.',
  [SIGN_IN_ERROR.signInFailed]: "We couldn't sign you in. Try again.",
  [SIGN_IN_ERROR.emailNotAllowed]: "This site doesn't accept sign-ins from that email address.",
};

/** The 403 the backend answers when the Sign-up allowlist refuses the email. */
function isEmailNotAllowed(err: unknown): boolean {
  return errorStatus(err) === 403 && errorMessage(err, '') === SIGN_IN_ERROR.emailNotAllowed;
}

export function Login() {
  const location = useLocation();
  const navigate = useNavigate();
  const [email, setEmail] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { sign_in_methods, operator, app_name } = useInstance();
  const offersGoogle = sign_in_methods.includes('google');
  const hasTerms = operator !== null;

  useEffect(() => {
    const code = new URLSearchParams(location.search).get('error');
    if (!isSignInErrorCode(code)) return;
    setError(SIGN_IN_ERROR_MESSAGES[code]);
    if (code === SIGN_IN_ERROR.invalidMagicLink) track('login_magic_link_invalid_shown');
    // Drop the code from the URL so a reload doesn't show the message again.
    window.history.replaceState({}, document.title, location.pathname);
  }, [location.search, location.pathname]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const domain = emailDomain(email);
    track('login_magic_link_submitted', { email_domain: domain });
    setLoading(true);
    setError(null);
    try {
      await authService.requestMagicLink(email);
      track('login_magic_link_requested_succeeded', { email_domain: domain });
      navigate('/login/magic-link/sent', { state: { email } });
    } catch (err) {
      const message = err instanceof Error ? err.message : 'unknown';
      track('login_magic_link_requested_failed', { error_message: message });
      setError(
        isEmailNotAllowed(err)
          ? SIGN_IN_ERROR_MESSAGES[SIGN_IN_ERROR.emailNotAllowed]
          : "We couldn't send the magic link. Try again in a moment.",
      );
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="grid min-h-screen bg-background text-foreground lg:grid-cols-2">
      <div className="flex flex-col">
        <main className="flex flex-1 items-center justify-center px-4 py-12">
          <div className="w-full max-w-[440px]">
            <div className="rounded-2xl border border-border bg-card p-8 shadow-raised sm:p-10">
              <img src={mascot} alt="" className="h-10 w-auto select-none" draggable={false} />
              <h1 className="mt-6 text-3xl font-normal leading-tight tracking-tight text-foreground">
                Welcome to {app_name}
              </h1>
              <p className="mt-3 text-base leading-relaxed text-muted-foreground">
                Write X posts in the style of the authors you choose.
              </p>

              <div className="mt-8 grid gap-6">
                {offersGoogle && (
                  <>
                    <GoogleAuthButton
                      variant="raisedNeutral"
                      className="h-11 text-base"
                      onError={() => setError("We couldn't start Google sign-in. Try again.")}
                    />
                    <div className="flex items-center gap-4 text-xs text-muted-foreground">
                      <div className="h-px flex-1 bg-border" />
                      or
                      <div className="h-px flex-1 bg-border" />
                    </div>
                  </>
                )}

                <form onSubmit={handleSubmit} className="space-y-4">
                  <div className="space-y-2">
                    <label
                      className="text-sm font-medium leading-none text-foreground"
                      htmlFor="email"
                    >
                      Email
                    </label>
                    <input
                      id="email"
                      type="email"
                      placeholder="you@example.com"
                      autoComplete="email"
                      required
                      disabled={loading}
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                      className="flex h-11 w-full rounded-lg border border-input bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:cursor-not-allowed disabled:opacity-50"
                    />
                  </div>
                  {error && (
                    <div
                      role="alert"
                      className="rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-sm font-medium text-destructive"
                    >
                      {error}
                    </div>
                  )}
                  <Button
                    type="submit"
                    variant="raised"
                    className="h-11 w-full text-base"
                    disabled={loading}
                  >
                    {loading ? 'Sending…' : 'Sign in with email'}
                  </Button>
                </form>
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
