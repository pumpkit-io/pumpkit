import { useCallback, useEffect, useId, useRef, useState, type ReactNode } from 'react';
import { Link, useLocation, useSearchParams } from 'react-router-dom';
import { Laptop, ShieldAlert, ShieldCheck, type LucideIcon } from 'lucide-react';
import { ErrorBanner } from '@/components/ErrorBanner';
import { Button } from '@/components/ui/button';
import { useAuth } from '@/contexts/AuthContext';
import { SubscribePrompt } from '@/features/billing/SubscribePrompt';
import { APP_HOME } from '@/features/onboarding/paths';
import { track } from '@/lib/analytics';
import { redirectTo } from '@/lib/navigation';
import { returnTo } from '@/lib/returnTo';
import { cn } from '@/lib/utils';
import { errorMessage, errorStatus } from '@/services/apiErrors';
import {
  oauthConsentService,
  type ConsentApp,
  type ConsentRequest,
} from '@/services/oauthConsentService';
import { useProfile } from './layout/ProfileContext';

export const OAUTH_CONSENT_PATH = '/oauth/consent';

/** The causes authorize names in `?error=` while the app's return address is still untrusted. */
const INVALID_CAUSE: Record<string, string> = {
  invalid_client: "The app isn't registered with Pumpkit.",
  invalid_redirect_uri: "The return address doesn't match what the app registered.",
};

const REQUEST_GONE =
  'This request expired or was already used. Start connecting again from your app.';

const HEADING_CLASS = 'font-sans text-2xl/[30px] font-semibold tracking-[-0.015em] text-foreground';

type Load =
  | { status: 'loading' }
  | { status: 'failed' }
  | { status: 'gone' }
  | { status: 'ready'; request: ConsentRequest };

type Decision = 'approve' | 'deny';

const eventProps = (app: ConsentApp) => ({
  verified: app.verifiedDomain !== null,
  local: app.isLocal,
});

function Column({ labelledBy, children }: { labelledBy?: string; children: ReactNode }) {
  return (
    <section aria-labelledby={labelledBy} className="max-w-[480px] space-y-6">
      {children}
    </section>
  );
}

/** A dead end with no buttons: the User starts again from the app. */
function Notice({ title, lines }: { title: string; lines: string[] }) {
  const headingId = useId();
  return (
    <Column labelledBy={headingId}>
      <div className="space-y-2">
        <h1 id={headingId} className={HEADING_CLASS}>
          {title}
        </h1>
        {lines.map((line) => (
          <p key={line} className="font-sans text-sm text-muted-foreground">
            {line}
          </p>
        ))}
      </div>
    </Column>
  );
}

function LoadingRequest() {
  return (
    <Column>
      <div role="status" aria-label="Loading the connection request" className="space-y-3">
        <div className="h-[30px] w-4/5 animate-pulse rounded-md bg-muted motion-reduce:animate-none" />
        <div className="h-5 w-1/2 animate-pulse rounded-md bg-muted motion-reduce:animate-none" />
      </div>
    </Column>
  );
}

function IdentityLine({
  icon: Icon,
  warning,
  strong,
  children,
}: {
  icon: LucideIcon;
  warning: boolean;
  strong?: boolean;
  children: ReactNode;
}) {
  return (
    <p
      className={cn(
        'flex items-center gap-2 font-sans',
        strong ? 'text-base font-semibold' : 'text-sm',
        warning ? 'text-warning' : 'text-foreground',
      )}
    >
      <Icon aria-hidden className="h-4 w-4 shrink-0" />
      <span className="min-w-0 break-words">{children}</span>
    </p>
  );
}

/** Who the app is and where it sends the User: the one thing on the page they must not miss. */
function Identity({ app }: { app: ConsentApp }) {
  const unverified = app.verifiedDomain === null;
  return (
    <div
      className={cn(
        'space-y-1.5 rounded-lg border px-4 py-3',
        unverified || app.isLocal ? 'border-warning/30 bg-warning/10' : 'border-border bg-muted/40',
      )}
    >
      <IdentityLine icon={unverified ? ShieldAlert : ShieldCheck} warning={unverified} strong>
        {unverified ? 'Unverified app' : `Verified: ${app.verifiedDomain}`}
      </IdentityLine>
      <IdentityLine icon={Laptop} warning={app.isLocal}>
        {app.isLocal ? 'An app on this computer' : `Sends you back to ${app.redirectHost}`}
      </IdentityLine>
    </div>
  );
}

function SignedInAs() {
  const profile = useProfile();
  const { logout } = useAuth();
  const location = useLocation();
  if (!profile) return null;

  const switchAccount = () => {
    returnTo.remember(location.pathname + location.search);
    void logout();
  };

  return (
    <p className="font-sans text-sm text-muted-foreground">
      Signed in as <span className="text-foreground">{profile.email}</span>{' '}
      <button
        type="button"
        className="rounded-sm text-foreground underline underline-offset-4 transition-opacity hover:opacity-70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        onClick={switchAccount}
      >
        Not you?
      </button>
    </p>
  );
}

function Ready({ id, app }: { id: string; app: ConsentApp }) {
  const headingId = useId();
  const [inFlight, setInFlight] = useState<Decision | null>(null);
  const [failure, setFailure] = useState<{ message: string; decision: Decision } | null>(null);
  const [needsSubscription, setNeedsSubscription] = useState(false);
  const [decided, setDecided] = useState<Decision | null>(null);
  const [gone, setGone] = useState(false);

  const decide = async (decision: Decision) => {
    if (inFlight) return;
    setInFlight(decision);
    setFailure(null);
    try {
      const url =
        decision === 'approve'
          ? await oauthConsentService.approve(id)
          : await oauthConsentService.deny(id);
      track(
        decision === 'approve' ? 'oauth_consent_approved' : 'oauth_consent_denied',
        eventProps(app),
      );
      redirectTo(url);
      // An app-scheme return address leaves the browser here.
      setDecided(decision);
    } catch (e) {
      const status = errorStatus(e);
      if (status === 404) setGone(true);
      else if (decision === 'approve' && status === 403) setNeedsSubscription(true);
      else {
        const fallback =
          decision === 'approve'
            ? `Couldn't connect ${app.name}. Check your connection and try again.`
            : "Couldn't cancel. Check your connection and try again.";
        setFailure({ message: errorMessage(e, fallback), decision });
      }
    } finally {
      setInFlight(null);
    }
  };

  if (gone) return <Notice title="This request has ended" lines={[REQUEST_GONE]} />;

  return (
    <Column labelledBy={headingId}>
      <div className="space-y-2">
        <h1 id={headingId} className={HEADING_CLASS}>
          Connect {app.name} to Pumpkit
        </h1>
        <SignedInAs />
      </div>

      {decided ? (
        <div className="space-y-3">
          <p className="font-sans text-sm text-foreground">
            {decided === 'approve' ? 'Done' : 'Cancelled'}. Return to {app.name}.
          </p>
          <Button asChild variant="outline" className="h-10">
            <Link to={APP_HOME}>Go to Pumpkit</Link>
          </Button>
        </div>
      ) : (
        <>
          <p className="font-sans text-sm text-foreground">
            {app.name} will be able to use Pumpkit as you: write and revise posts, manage your
            inspiration authors, schedule posts and publish them on X. It can&apos;t see your
            password or change your subscription.
          </p>
          <Identity app={app} />
          {failure && (
            <ErrorBanner message={failure.message} onRetry={() => void decide(failure.decision)} />
          )}
          {needsSubscription ? (
            <SubscribePrompt message="Connecting an app needs a subscription." />
          ) : (
            <div className="flex gap-2">
              <Button
                type="button"
                className="h-10"
                disabled={inFlight !== null}
                onClick={() => void decide('approve')}
              >
                Allow
              </Button>
              <Button
                type="button"
                variant="outline"
                className="h-10"
                disabled={inFlight !== null}
                onClick={() => void decide('deny')}
              >
                Cancel
              </Button>
            </div>
          )}
          <p className="font-sans text-xs text-muted-foreground">
            Only allow apps you trust. You can disconnect it anytime in Settings.
          </p>
        </>
      )}
    </Column>
  );
}

/** Loads the request once per attempt and reports each app shown once. */
function useConsentRequest(id: string | null) {
  const [load, setLoad] = useState<Load>({ status: 'loading' });
  const [attempt, setAttempt] = useState(0);
  const viewed = useRef<string | null>(null);

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    setLoad({ status: 'loading' });
    oauthConsentService
      .get(id)
      .then((request) => {
        if (cancelled) return;
        setLoad({ status: 'ready', request });
        if (viewed.current === id) return;
        viewed.current = id;
        track('oauth_consent_viewed', eventProps(request.app));
      })
      .catch((e: unknown) => {
        if (!cancelled) setLoad({ status: errorStatus(e) === 404 ? 'gone' : 'failed' });
      });
    return () => {
      cancelled = true;
    };
  }, [id, attempt]);

  const retry = useCallback(() => setAttempt((n) => n + 1), []);
  return { load, retry };
}

/**
 * Where an app's authorize link lands: the User reads who is asking and allows or cancels.
 * Outside the Onboarding gate (ADR 0020), so it renders for every signed-in User.
 */
export function OAuthConsent() {
  const [params] = useSearchParams();
  const errorCode = params.get('error');
  const id = errorCode === null ? params.get('request') : null;
  const { load, retry } = useConsentRequest(id);

  if (!id) {
    const cause = errorCode ? INVALID_CAUSE[errorCode] : undefined;
    return (
      <Notice
        title="This connection request isn't valid"
        lines={[...(cause ? [cause] : []), 'Try connecting again from the app.']}
      />
    );
  }
  if (load.status === 'loading') return <LoadingRequest />;
  if (load.status === 'gone')
    return <Notice title="This request has ended" lines={[REQUEST_GONE]} />;
  if (load.status === 'failed') {
    return (
      <Column>
        <ErrorBanner message="Couldn't load this connection request." onRetry={retry} />
      </Column>
    );
  }
  return <Ready key={id} id={id} app={load.request.app} />;
}
