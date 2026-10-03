import { useState, useEffect } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { Button } from '../components/ui/button';
import { GoogleAuthButton } from '../components/google/GoogleAuthButton';
import { authService } from '../services/authService';
import { track } from '../lib/analytics';

function emailDomain(email: string): string {
  const at = email.lastIndexOf('@');
  return at >= 0 ? email.slice(at + 1).toLowerCase() : 'unknown';
}

export function Login() {
  const location = useLocation();
  const navigate = useNavigate();
  const [email, setEmail] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const urlParams = new URLSearchParams(location.search);
    if (urlParams.get('error') === 'invalid_magic_link') {
      setError('That sign-in link is invalid or has expired. Please request a new one.');
      track('login_magic_link_invalid_shown');
      window.history.replaceState({}, document.title, location.pathname);
    }
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
      setError("We couldn't send the link. Please try again in a moment.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-4 text-foreground">
      <div className="w-full max-w-[380px]">
        <div className="rounded-xl border border-border bg-card">
          <div className="flex flex-col space-y-1.5 p-6">
            <h2 className="text-3xl font-normal leading-none tracking-tight text-foreground">
              Welcome back
            </h2>
            <p className="text-sm text-muted-foreground">Choose your preferred sign in method</p>
          </div>
          <div className="p-6 pt-0">
            <div className="grid gap-6">
              <GoogleAuthButton onError={() => {}} />
              <div className="relative">
                <div className="absolute inset-0 flex items-center">
                  <div className="h-px w-full shrink-0 bg-border" />
                </div>
                <div className="relative flex justify-center text-xs uppercase tracking-wider">
                  <span className="bg-card px-2 text-muted-foreground normal-case">or</span>
                </div>
              </div>

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
                    placeholder="steve.jobs@gmail.com"
                    autoComplete="email"
                    required
                    disabled={loading}
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    className="flex h-10 w-full rounded-lg border border-input bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:cursor-not-allowed disabled:opacity-50"
                  />
                </div>
                {error && (
                  <div className="rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-sm font-medium text-destructive">
                    {error}
                  </div>
                )}
                <Button type="submit" className="w-full" disabled={loading || !email}>
                  {loading ? 'Sending…' : 'Sign in with email'}
                </Button>
              </form>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
