import posthog, { type PostHogConfig } from 'posthog-js';

const enabled = import.meta.env.VITE_POSTHOG_ENABLED === 'true';
const apiKey = import.meta.env.VITE_POSTHOG_KEY ?? '';
const host = import.meta.env.VITE_POSTHOG_HOST ?? 'https://eu.i.posthog.com';
const uiHost = import.meta.env.VITE_POSTHOG_UI_HOST ?? 'https://eu.posthog.com';

let initialised = false;

/**
 * Initialise PostHog once. No-op if VITE_POSTHOG_ENABLED !== 'true' or the
 * API key is missing — keeps local dev quiet by default and prevents bogus
 * "no project" errors on environments that haven't configured the keys yet.
 */
export function initPostHog(): void {
  if (initialised || !enabled || !apiKey) return;
  const config: Partial<PostHogConfig> = {
    api_host: host,
    // In prod point VITE_POSTHOG_HOST at the Caddy relay (https://<domain>/ph-relay) so events bypass adblockers; ui_host keeps dashboard links pointing at PostHog.
    ui_host: uiHost,
    // Only create person profiles for authenticated users — cheaper and
    // keeps anonymous traffic out of the persons table.
    person_profiles: 'identified_only',
    // Autocapture handles clicks/inputs/form submits. We manually capture
    // SPA pageviews via the router tracker because autocapture only fires
    // on the initial page load.
    capture_pageview: false,
    capture_pageleave: true,
    session_recording: {
      maskAllInputs: true,
    },
    // PostHog auto-captures JS errors for Error Tracking.
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
