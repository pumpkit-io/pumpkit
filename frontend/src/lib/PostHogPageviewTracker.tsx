import { useEffect } from 'react';
import { useLocation } from 'react-router-dom';
import { capturePageview } from './posthog';

/**
 * Capture SPA route changes as PostHog `$pageview` events. PostHog autocapture
 * only fires `$pageview` on the initial document load — react-router navigations
 * don't trigger a page load, so we forward them here.
 *
 * Must be mounted *inside* `<Router>` to have access to `useLocation()`.
 */
export function PostHogPageviewTracker(): null {
  const location = useLocation();
  useEffect(() => {
    capturePageview(location.pathname + location.search);
  }, [location.pathname, location.search]);
  return null;
}
