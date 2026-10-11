import { useEffect } from 'react';
import { useLocation } from 'react-router-dom';
import { capturePageview, useAnalyticsConsent } from './analyticsConsent';

/**
 * Sends react-router navigations as `$pageview`: autocapture only fires it on the initial document load.
 * Also sends the page on screen when the visitor accepts analytics. Must be mounted inside `<Router>`.
 */
export function PostHogPageviewTracker(): null {
  const location = useLocation();
  const consent = useAnalyticsConsent();
  useEffect(() => {
    capturePageview(location.pathname + location.search);
  }, [location.pathname, location.search, consent]);
  return null;
}
