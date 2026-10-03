import { useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { Button } from '../components/ui/button';
import { authService } from '../services/authService';
import { Eye, EyeOff } from 'lucide-react';

const inputClass =
  'flex h-10 w-full rounded-lg border border-input bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:cursor-not-allowed disabled:opacity-50';

export function ResetPassword() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const token = searchParams.get('token') ?? '';
  const tokenMissing = token.trim().length === 0;

  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState<{ type: 'success' | 'error'; message: string } | null>(null);
  const [showNewPassword, setShowNewPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    if (!token) {
      setStatus({ type: 'error', message: 'Reset token is missing or invalid.' });
      return;
    }

    if (newPassword !== confirmPassword) {
      setStatus({ type: 'error', message: 'Passwords do not match.' });
      return;
    }

    setLoading(true);
    setStatus(null);

    try {
      const response = await authService.resetPassword({
        token,
        new_password: newPassword,
      });

      navigate('/login', {
        replace: true,
        state: {
          passwordResetSuccess: true,
          message: response.message,
          email: response.email,
        },
      });
    } catch (error: any) {
      const message =
        error?.response?.data?.detail ?? 'Unable to reset password. Please try again.';
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
              Choose a new password
            </h2>
            <p className="text-sm text-muted-foreground">
              Enter and confirm your new password below.
            </p>
          </div>
          <div className="p-6 pt-0">
            <form onSubmit={handleSubmit} className="space-y-6">
              <div className="space-y-2">
                <label
                  className="text-sm font-medium leading-none text-foreground"
                  htmlFor="new-password"
                >
                  New password
                </label>
                <div className="relative">
                  <input
                    id="new-password"
                    type={showNewPassword ? 'text' : 'password'}
                    autoComplete="new-password"
                    required
                    disabled={loading}
                    value={newPassword}
                    onChange={(event) => {
                      const value = event.target.value;
                      setNewPassword(value);
                      if (!value) {
                        setShowNewPassword(false);
                      }
                    }}
                    className={`${inputClass} ${newPassword ? 'pr-10' : ''}`}
                  />
                  {newPassword && (
                    <button
                      type="button"
                      onClick={() => setShowNewPassword((prev) => !prev)}
                      className="absolute inset-y-0 right-2 flex items-center text-muted-foreground transition-colors hover:text-foreground"
                      aria-label={showNewPassword ? 'Hide password' : 'Show password'}
                    >
                      {showNewPassword ? (
                        <EyeOff className="h-5 w-5" />
                      ) : (
                        <Eye className="h-5 w-5" />
                      )}
                    </button>
                  )}
                </div>
              </div>

              <div className="space-y-2">
                <label
                  className="text-sm font-medium leading-none text-foreground"
                  htmlFor="confirm-password"
                >
                  Confirm password
                </label>
                <div className="relative">
                  <input
                    id="confirm-password"
                    type={showConfirmPassword ? 'text' : 'password'}
                    autoComplete="new-password"
                    required
                    disabled={loading}
                    value={confirmPassword}
                    onChange={(event) => {
                      const value = event.target.value;
                      setConfirmPassword(value);
                      if (!value) {
                        setShowConfirmPassword(false);
                      }
                    }}
                    className={`${inputClass} ${confirmPassword ? 'pr-10' : ''}`}
                  />
                  {confirmPassword && (
                    <button
                      type="button"
                      onClick={() => setShowConfirmPassword((prev) => !prev)}
                      className="absolute inset-y-0 right-2 flex items-center text-muted-foreground transition-colors hover:text-foreground"
                      aria-label={showConfirmPassword ? 'Hide password' : 'Show password'}
                    >
                      {showConfirmPassword ? (
                        <EyeOff className="h-5 w-5" />
                      ) : (
                        <Eye className="h-5 w-5" />
                      )}
                    </button>
                  )}
                </div>
              </div>

              {tokenMissing && (
                <div className="rounded-lg border border-border bg-muted p-3 text-sm text-muted-foreground">
                  This reset link is missing or invalid. Request a new password reset from the sign
                  in page.
                </div>
              )}

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

              <Button type="submit" className="w-full" disabled={loading || tokenMissing}>
                {loading ? 'Updating password…' : 'Update password'}
              </Button>
            </form>
          </div>
        </div>
        <p className="mt-4 text-center text-sm text-muted-foreground">
          Need to go back?{' '}
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
