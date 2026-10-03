import { useEffect } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { ArrowLeft, ArrowUpRight } from 'lucide-react';
import { Button } from '../components/ui/button';
import { Brand } from '@/components/brand/Brand';
import { isGmailAddress } from '../lib/gmailSearch';

type MagicLinkSentState = { email?: string };

const API_URL = import.meta.env.VITE_API_URL;
const INBOX_REDIRECT_URL = `${API_URL}/login/magic-link/inbox-redirect`;
const SUPPORT_CONTACT_URL = `${API_URL}/support/contact`;

export function MagicLinkSent() {
  const navigate = useNavigate();
  const location = useLocation();
  const state = (location.state ?? {}) as MagicLinkSentState;
  const email = typeof state.email === 'string' ? state.email : '';

  useEffect(() => {
    if (!email) {
      navigate('/login', { replace: true });
    }
  }, [email, navigate]);

  if (!email) {
    return null;
  }

  const showGmailButton = isGmailAddress(email);

  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-4 text-foreground">
      <div className="w-full max-w-[380px]">
        <button
          type="button"
          aria-label="Back to sign in"
          onClick={() => navigate('/login')}
          className="mb-4 inline-flex items-center gap-2 rounded-lg border border-border bg-card px-3 py-1.5 text-sm font-medium text-foreground transition-colors hover:bg-accent"
        >
          <ArrowLeft className="h-4 w-4" />
          Sign in
        </button>

        <div className="rounded-xl border border-border bg-card">
          <div className="flex items-center justify-center gap-2 border-b border-border p-6">
            <Brand />
          </div>

          <div className="flex flex-col items-center gap-4 p-6 text-center">
            <h2 className="text-3xl font-normal leading-none tracking-tight text-foreground">
              Magic link sent
            </h2>
            <p className="text-sm leading-relaxed text-muted-foreground">
              Check your inbox for <strong className="font-medium text-foreground">{email}</strong>{' '}
              and click the link to sign in.
            </p>

            {showGmailButton && (
              <Button asChild className="mt-2 w-full">
                <a href={INBOX_REDIRECT_URL} target="_blank" rel="noopener noreferrer">
                  Open Gmail inbox
                  <ArrowUpRight className="ml-1 h-4 w-4" />
                </a>
              </Button>
            )}
          </div>
        </div>

        <p className="mt-6 text-center text-sm text-muted-foreground">
          Can't find it? Check your spam folder. Still need help?{' '}
          <a
            href={SUPPORT_CONTACT_URL}
            className="text-foreground underline underline-offset-4 hover:opacity-70 transition-opacity"
          >
            Contact support
          </a>
          .
        </p>
      </div>
    </div>
  );
}
