import { useEffect, useRef, useState } from 'react';
import { Button } from '@/components/ui/button';
import { PRIVACY_PATH } from '@/features/legal/documents';
import {
  grantAnalyticsConsent,
  onCookieSettingsOpened,
  refuseAnalyticsConsent,
  useAnalyticsConsent,
} from '@/lib/analyticsConsent';

/** Asks for Analytics consent while this browser has no choice stored, or when Cookie settings reopens it. */
export function ConsentBanner() {
  const consent = useAnalyticsConsent();
  const [reopened, setReopened] = useState(false);
  const regionRef = useRef<HTMLElement>(null);

  useEffect(() => onCookieSettingsOpened(() => setReopened(true)), []);

  useEffect(() => {
    // Keyboard users who opened Cookie settings land on the choice, not back at the footer.
    if (reopened) regionRef.current?.focus();
  }, [reopened]);

  if (consent !== null && !reopened) return null;

  const choose = (accept: boolean) => {
    setReopened(false);
    if (accept) grantAnalyticsConsent();
    else refuseAnalyticsConsent();
  };

  return (
    <section
      ref={regionRef}
      tabIndex={-1}
      aria-label="Analytics consent"
      className="fixed inset-x-4 bottom-4 z-50 mx-auto max-w-xl rounded-lg border border-border bg-background p-5 text-foreground shadow-lg focus:outline-none sm:inset-x-6"
    >
      <h2 className="text-sm font-semibold">Allow analytics?</h2>
      <p className="mt-2 text-sm leading-6 text-muted-foreground">
        If you accept, PostHog records the pages you view, what you click and a session recording
        with typed text masked, so Pumpkit can see how it is used and find problems. Pumpkit works
        the same if you reject.{' '}
        <a
          href={`${PRIVACY_PATH}#cookies`}
          target="_blank"
          rel="noopener"
          className="text-foreground underline underline-offset-4"
        >
          How Pumpkit uses cookies
        </a>
      </p>
      <div className="mt-4 grid grid-cols-2 gap-3">
        <Button variant="outline" onClick={() => choose(false)}>
          Reject
        </Button>
        <Button variant="outline" onClick={() => choose(true)}>
          Accept
        </Button>
      </div>
    </section>
  );
}
