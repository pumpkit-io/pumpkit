import { useEffect } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { ArrowLeft, ArrowUpRight, MailCheck } from 'lucide-react';
import { Button } from '../components/ui/button';
import { useInstance } from '@/features/instance/useInstance';
import { TEXT_LINK_CLASS } from '@/features/legal/textLink';
import { AUTH_HEADING_CLASS, AuthShell } from './layout/AuthShell';
import { API_BASE_URL } from '@/lib/api';
import { isGmailAddress } from '../lib/gmailSearch';

type MagicLinkSentState = { email?: string };

const INBOX_REDIRECT_URL = `${API_BASE_URL}/login/magic-link/inbox-redirect`;
const SUPPORT_CONTACT_URL = `${API_BASE_URL}/support/contact`;

export function MagicLinkSent() {
  const navigate = useNavigate();
  const location = useLocation();
  const state = (location.state ?? {}) as MagicLinkSentState;
  const email = typeof state.email === 'string' ? state.email : '';
  const { support_email } = useInstance();

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
    <AuthShell>
      <div className="space-y-8">
        <div className="space-y-4">
          <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10 text-primary">
            <MailCheck aria-hidden className="h-5 w-5" />
          </span>
          <div className="space-y-2">
            <h1 className={AUTH_HEADING_CLASS}>Magic link sent</h1>
            <p className="font-sans text-sm leading-relaxed text-muted-foreground">
              Check your inbox for{' '}
              <strong className="break-all font-medium text-foreground">{email}</strong> and click
              the link to sign in.
            </p>
          </div>
        </div>

        {showGmailButton && (
          <Button asChild className="w-full">
            <a href={INBOX_REDIRECT_URL} target="_blank" rel="noopener noreferrer">
              Open Gmail inbox
              <ArrowUpRight aria-hidden className="ml-1 h-4 w-4" />
            </a>
          </Button>
        )}

        <div className="space-y-3 border-t border-border pt-5 font-sans text-sm text-muted-foreground">
          <p>
            Can't find it? Check your spam folder.
            {support_email && (
              <>
                {' '}
                Still need help?{' '}
                <a href={SUPPORT_CONTACT_URL} className={TEXT_LINK_CLASS}>
                  Contact support
                </a>
                .
              </>
            )}
          </p>
          <button
            type="button"
            onClick={() => navigate('/login')}
            className="inline-flex items-center gap-1.5 rounded-sm font-medium text-foreground underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <ArrowLeft aria-hidden className="h-4 w-4" />
            Back to sign in
          </button>
        </div>
      </div>
    </AuthShell>
  );
}
