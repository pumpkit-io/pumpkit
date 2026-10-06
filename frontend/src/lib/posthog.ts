import posthog, { type PostHogConfig } from 'posthog-js';

const enabled = import.meta.env.VITE_POSTHOG_ENABLED === 'true';
const apiKey = import.meta.env.VITE_POSTHOG_KEY ?? '';
const host = import.meta.env.VITE_POSTHOG_HOST ?? 'https://eu.i.posthog.com';
const uiHost = import.meta.env.VITE_POSTHOG_UI_HOST ?? 'https://eu.posthog.com';

let initialised = false;

/**
 * No-op unless VITE_POSTHOG_ENABLED is 'true' and a key is set.
 * Keeps local dev quiet and avoids "no project" errors where keys aren't configured.
 */
export function initPostHog(): void {
  if (initialised || !enabled || !apiKey) return;
  const config: Partial<PostHogConfig> = {
    api_host: host,
    // In prod point VITE_POSTHOG_HOST at the Caddy relay (https://<domain>/ph-relay) so events bypass adblockers; ui_host keeps dashboard links pointing at PostHog.
    ui_host: uiHost,
    // Cheaper, and keeps anonymous traffic out of the persons table.
    person_profiles: 'identified_only',
    // Autocapture only fires $pageview on initial load; PostHogPageviewTracker covers SPA navigations.
    capture_pageview: false,
    capture_pageleave: true,
    session_recording: {
      maskAllInputs: true,
    },
    capture_exceptions: true,
  };
  posthog.init(apiKey, config);
  initialised = true;
}

export function identifyUser(distinctId: string, properties?: Record<string, unknown>): void {
  if (!initialised) return;
  posthog.identify(distinctId, properties);
}

export function resetPostHog(): void {
  if (!initialised) return;
  posthog.reset();
}

export function capturePageview(path: string): void {
  if (!initialised) return;
  posthog.capture('$pageview', { $current_url: window.location.origin + path });
}

export { posthog };
