import { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { Button } from '../components/ui/button';
import { authService, SignupResponse } from '../services/authService';
import { Check, X, Eye, EyeOff } from 'lucide-react';

interface ItemRowProps {
  checked: boolean;
  label: string;
}

function ItemRow({ checked, label }: ItemRowProps) {
  return (
    <div className="flex items-center space-x-2 text-xs">
      {checked ? (
        <Check className="h-3 w-3 text-foreground" />
      ) : (
        <X className="h-3 w-3 text-muted-foreground" />
      )}
      <span className={checked ? 'text-foreground' : 'text-muted-foreground'}>{label}</span>
    </div>
  );
}

const inputClass =
  'flex h-10 w-full rounded-lg border border-input bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:cursor-not-allowed disabled:opacity-50';
const errorClass =
  'rounded-lg border border-destructive/30 bg-destructive/10 p-2 text-sm font-medium text-destructive';

export function Signup() {
  const navigate = useNavigate();
  const [firstName, setFirstName] = useState('');
  const [lastName, setLastName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [showPassword, setShowPassword] = useState(false);
  const [showResendVerification, setShowResendVerification] = useState(false);
  const [resendLoading, setResendLoading] = useState(false);
  const [resendSuccess, setResendSuccess] = useState(false);

  const [passwordCriteria, setPasswordCriteria] = useState({
    length: false,
    uppercase: false,
    lowercase: false,
    number: false,
    special: false
  });

  const handlePasswordChange = (value: string) => {
    setPassword(value);
    setPasswordCriteria({
      length: value.length >= 8 && value.length <= 50,
      uppercase: /[A-Z]/.test(value),
      lowercase: /[a-z]/.test(value),
      number: /[0-9]/.test(value),
      special: /[^A-Za-z0-9]/.test(value)
    });

    if (!value) {
      setShowPassword(false);
    }
  };

  const validateForm = () => {
    const newErrors: Record<string, string> = {};
    const trimmedFirstName = firstName.trim();
    const trimmedLastName = lastName.trim();
    const trimmedEmail = email.trim();

    if (!trimmedFirstName) {
      newErrors.firstName = 'First name is required';
    } else if (trimmedFirstName.length < 2) {
      newErrors.firstName = 'First name must be at least 2 characters';
    } else if (trimmedFirstName.length > 300) {
      newErrors.firstName = 'First name must be at most 300 characters';
    }

    if (!trimmedLastName) {
      newErrors.lastName = 'Last name is required';
    } else if (trimmedLastName.length < 2) {
      newErrors.lastName = 'Last name must be at least 2 characters';
    } else if (trimmedLastName.length > 300) {
      newErrors.lastName = 'Last name must be at most 300 characters';
    }

    if (!trimmedEmail) {
      newErrors.email = 'Email is required';
    } else if (trimmedEmail.length > 320) {
      newErrors.email = 'Email must be at most 320 characters';
    } else if (!/\S+@\S+\.\S+/.test(trimmedEmail)) {
      newErrors.email = 'Invalid email address';
    }

    if (!password) {
      newErrors.password = 'Password is required';
    } else if (password.length < 8) {
      newErrors.password = 'Password must be at least 8 characters';
    } else if (password.length > 50) {
      newErrors.password = 'Password must be at most 50 characters';
    } else if (!/[0-9]/.test(password)) {
      newErrors.password = 'Password must contain at least one number';
    } else if (!/[A-Z]/.test(password)) {
      newErrors.password = 'Password must contain at least one uppercase letter';
    } else if (!/[a-z]/.test(password)) {
      newErrors.password = 'Password must contain at least one lowercase letter';
    } else if (!/[^A-Za-z0-9]/.test(password)) {
      newErrors.password = 'Password must contain at least one special character';
    }

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!validateForm()) {
      return;
    }

    setLoading(true);

    try {
      const result: SignupResponse = await authService.register({
        first_name: firstName,
        last_name: lastName,
        email,
        password
      });

      navigate('/login', {
        state: {
          signupSuccess: true,
          message: result.message,
          email: result.email
        }
      });
    } catch (err: any) {
      if (err.response?.data?.detail) {
        if (typeof err.response.data.detail === 'string') {
          const detail = err.response.data.detail;
          setErrors({ form: detail });
          if (detail === 'Email already registered. We sent you an email to confirm your account before signing in.') {
            setShowResendVerification(true);
            setResendSuccess(false);
          } else {
            setShowResendVerification(false);
          }
        } else if (Array.isArray(err.response.data.detail)) {
          const fieldErrors: Record<string, string> = {};
          err.response.data.detail.forEach((error: any) => {
            if (error.loc && error.loc[1] && error.msg) {
              fieldErrors[error.loc[1]] = error.msg;
            }
          });
          setErrors(fieldErrors);
          setShowResendVerification(false);
        }
      } else {
        setErrors({ form: 'Failed to create account. Please try again.' });
        setShowResendVerification(false);
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-4 text-foreground">
      <div className="w-full max-w-[420px]">
        <div className="rounded-xl border border-border bg-card">
          <div className="flex flex-col space-y-1.5 p-6">
            <h2 className="text-3xl font-normal leading-none tracking-tight text-foreground">Create an account</h2>
            <p className="text-sm text-muted-foreground">
              Enter your details to get started
            </p>
          </div>
          <div className="p-6 pt-0">
            <form onSubmit={handleSubmit} className="space-y-6">
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-2">
                  <label className="text-sm font-medium leading-none text-foreground" htmlFor="firstName">
                    First name
                  </label>
                  <input
                    id="firstName"
                    type="text"
                    placeholder="Steve"
                    disabled={loading}
                    value={firstName}
                    onChange={(e) => setFirstName(e.target.value)}
                    maxLength={300}
                    className={inputClass}
                  />
                  {errors.firstName && <div className={errorClass}>{errors.firstName}</div>}
                </div>
                <div className="space-y-2">
                  <label className="text-sm font-medium leading-none text-foreground" htmlFor="lastName">
                    Last name
                  </label>
                  <input
                    id="lastName"
                    type="text"
                    placeholder="Jobs"
                    disabled={loading}
                    value={lastName}
                    onChange={(e) => setLastName(e.target.value)}
                    maxLength={300}
                    className={inputClass}
                  />
                  {errors.lastName && <div className={errorClass}>{errors.lastName}</div>}
                </div>
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium leading-none text-foreground" htmlFor="email">
                  Email
                </label>
                <input
                  id="email"
                  type="email"
                  placeholder="steve.jobs@gmail.com"
                  autoComplete="email"
                  disabled={loading}
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  maxLength={320}
                  className={inputClass}
                />
                {errors.email && <div className={errorClass}>{errors.email}</div>}
              </div>
              <div className="space-y-3">
                <div className="space-y-2">
                  <label className="text-sm font-medium leading-none text-foreground" htmlFor="password">
                    Password
                  </label>
                  <div className="relative">
                    <input
                      id="password"
                      type={showPassword ? 'text' : 'password'}
                      autoComplete="new-password"
                      disabled={loading}
                      value={password}
                      onChange={(e) => handlePasswordChange(e.target.value)}
                      className={`${inputClass} ${password ? 'pr-10' : ''}`}
                    />
                    {password && (
                      <button
                        type="button"
                        onClick={() => setShowPassword((prev) => !prev)}
                        className="absolute inset-y-0 right-2 flex items-center text-muted-foreground transition-colors hover:text-foreground"
                        aria-label={showPassword ? 'Hide password' : 'Show password'}
                      >
                        {showPassword ? <EyeOff className="h-5 w-5" /> : <Eye className="h-5 w-5" />}
                      </button>
                    )}
                  </div>
                </div>

                {password && (
                  <div className="rounded-xl border border-border bg-muted p-4">
                    <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                      Password must contain
                    </div>
                    <div className="mt-3 grid gap-2">
                      <ItemRow checked={passwordCriteria.length} label="8-50 characters" />
                      <ItemRow checked={passwordCriteria.uppercase} label="One uppercase letter" />
                      <ItemRow checked={passwordCriteria.lowercase} label="One lowercase letter" />
                      <ItemRow checked={passwordCriteria.number} label="One number" />
                      <ItemRow checked={passwordCriteria.special} label="One special character" />
                    </div>
                  </div>
                )}

                {errors.password && <div className={errorClass}>{errors.password}</div>}
              </div>
              {errors.form && (
                <div className="rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-sm font-medium text-destructive">
                  {errors.form}
                </div>
              )}
              {showResendVerification && !resendSuccess && (
                <button
                  type="button"
                  disabled={resendLoading}
                  onClick={async () => {
                    setResendLoading(true);
                    try {
                      await authService.resendConfirmationEmail(email);
                      setResendSuccess(true);
                      setErrors({});
                    } catch {
                      setErrors({ form: 'Failed to resend confirmation email. Please try again later.' });
                    } finally {
                      setResendLoading(false);
                    }
                  }}
                  className="text-sm text-foreground underline underline-offset-4 transition-opacity hover:opacity-70 disabled:opacity-50"
                >
                  {resendLoading ? 'Sending…' : 'Resend confirmation email'}
                </button>
              )}
              {resendSuccess && (
                <div className="rounded-lg border border-border bg-muted p-3 text-sm font-medium text-foreground">
                  Confirmation email sent. Please check your inbox.
                </div>
              )}
              <Button
                type="submit"
                className="w-full"
                disabled={loading}
              >
                {loading ? 'Creating account…' : 'Create account'}
              </Button>
            </form>
          </div>
        </div>
        <p className="mt-4 text-center text-sm text-muted-foreground">
          Already have an account?{' '}
          <Link to="/login" className="text-foreground underline underline-offset-4 hover:opacity-70 transition-opacity">
            Sign in
          </Link>
        </p>
      </div>
    </div>
  );
}
