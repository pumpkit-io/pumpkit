import { useEffect } from 'react';
import { useLocation } from 'react-router-dom';
import { capturePageview } from './posthog';

/**
 * Sends react-router navigations as `$pageview`: autocapture only fires it on the initial document load.
 * Must be mounted inside `<Router>`.
 */
export function PostHogPageviewTracker(): null {
  const location = useLocation();
  useEffect(() => {
    capturePageview(location.pathname + location.search);
  }, [location.pathname, location.search]);
  return null;
}
