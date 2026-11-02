import { useState, useEffect } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { Button } from '../components/ui/button';
import { GoogleAuthButton } from '../components/google/GoogleAuthButton';
import { CircleAlert } from 'lucide-react';
import { Input } from '@/components/ui/input';
import { AUTH_HEADING_CLASS, AuthShell } from './layout/AuthShell';
import { useInstance } from '@/features/instance/useInstance';
import { PRIVACY_PATH, TERMS_PATH } from '@/features/legal/documents';
import { TEXT_LINK_CLASS } from '@/features/legal/textLink';
import { authService } from '../services/authService';
import { errorMessage, errorStatus } from '../services/apiErrors';
import { track } from '../lib/analytics';
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
  const { sign_in_methods, operator } = useInstance();
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
    <AuthShell>
      <div className="space-y-8">
        <div className="space-y-2">
          <h1 className={AUTH_HEADING_CLASS}>Welcome back</h1>
          <p className="font-sans text-sm text-muted-foreground">
            {offersGoogle
              ? 'Sign in with Google or a magic link sent to your email.'
              : 'Sign in with a magic link sent to your email.'}
          </p>
        </div>

        <div className="space-y-5">
          {offersGoogle && (
            <>
              <GoogleAuthButton
                onError={() => setError("We couldn't start Google sign-in. Try again.")}
              />
              <div className="flex items-center gap-3 text-xs text-muted-foreground">
                <div className="h-px flex-1 bg-border" />
                or
                <div className="h-px flex-1 bg-border" />
              </div>
            </>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-1.5">
              <label className="font-sans text-sm font-medium text-foreground" htmlFor="email">
                Email
              </label>
              <Input
                id="email"
                type="email"
                placeholder="you@example.com"
                autoComplete="email"
                required
                disabled={loading}
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </div>
            {error && (
              <div
                role="alert"
                className="flex gap-2 rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive"
              >
                <CircleAlert aria-hidden className="mt-0.5 h-4 w-4 shrink-0" />
                <span className="min-w-0 break-words">{error}</span>
              </div>
            )}
            <Button type="submit" className="w-full" disabled={loading || !email}>
              {loading ? 'Sending…' : 'Email me a magic link'}
            </Button>
          </form>
        </div>

        {/* Informational only: Users accept the Terms at checkout (ADR 0010). */}
        {hasTerms && (
          <p className="text-xs leading-5 text-muted-foreground">
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
    </AuthShell>
  );
}
