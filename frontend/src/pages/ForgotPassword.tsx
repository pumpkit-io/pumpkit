import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Button } from '../components/ui/button';
import { authService } from '../services/authService';

export function ForgotPassword() {
  const [email, setEmail] = useState('');
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState<{ type: 'success' | 'error'; message: string } | null>(null);

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setStatus(null);
    setLoading(true);

    try {
      const response = await authService.requestPasswordReset({ email });
      setStatus({ type: 'success', message: response.message });
      setEmail('');
    } catch (error: any) {
      const message =
        error?.response?.data?.detail ?? 'Unable to send reset instructions. Please try again.';
      setStatus({ type: 'error', message });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-4 text-foreground">
      <div className="w-full max-w-[420px]">
        <div className="rounded-xl border border-border bg-card">
          <div className="flex flex-col space-y-1.5 p-6">
            <h2 className="text-3xl font-normal leading-none tracking-tight text-foreground">
              Reset your password
            </h2>
            <p className="text-sm text-muted-foreground">
              Enter your email and we'll send you a reset link.
            </p>
          </div>
          <div className="p-6 pt-0">
            <form onSubmit={handleSubmit} className="space-y-6">
              <div className="space-y-2">
                <label className="text-sm font-medium leading-none text-foreground" htmlFor="email">
                  Email
                </label>
                <input
                  id="email"
                  type="email"
                  autoComplete="email"
                  required
                  disabled={loading}
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  className="flex h-10 w-full rounded-lg border border-input bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:cursor-not-allowed disabled:opacity-50"
                />
              </div>

              {status && (
                <div
                  className={
                    status.type === 'success'
                      ? 'rounded-lg border border-border bg-muted p-3 text-sm font-medium text-foreground'
                      : 'rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-sm font-medium text-destructive'
                  }
                >
                  {status.message}
                </div>
              )}

              <Button type="submit" className="w-full" disabled={loading}>
                {loading ? 'Sending reset link…' : 'Send reset link'}
              </Button>
            </form>
          </div>
        </div>
        <p className="mt-4 text-center text-sm text-muted-foreground">
          Remembered your password?{' '}
          <Link
            to="/login"
            className="text-foreground underline underline-offset-4 hover:opacity-70 transition-opacity"
          >
            Back to sign in
          </Link>
        </p>
      </div>
    </div>
  );
}
