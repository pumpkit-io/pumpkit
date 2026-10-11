import { useSyncExternalStore } from 'react';
import posthog, { type PostHogConfig } from 'posthog-js';
import { storage, storageKey } from './storage';

/**
 * Analytics consent (ADR 0009): the only way into PostHog. PostHog is initialised,
 * identifies, captures and records only while this browser's stored choice is `granted`.
 */

export type AnalyticsConsent = 'granted' | 'denied';

/**
 * The sessionStorage key (per tab) marking that analytics already identified
 * the User in this Session. Ending a Session or withdrawing consent clears it.
 */
export const POSTHOG_IDENTIFIED_KEY = storageKey('posthog-identified');

// PostHog's own cookies and storage entries all start with one of these.
const POSTHOG_PREFIXES = ['ph_', '__ph_'];

type Listener = () => void;
const consentListeners = new Set<Listener>();
const settingsListeners = new Set<Listener>();

let superProperties: Record<string, unknown> = {};

export function getAnalyticsConsent(): AnalyticsConsent | null {
  const value = storage.get<unknown>('analytics-consent', null);
  return value === 'granted' || value === 'denied' ? value : null;
}

function capturing(): boolean {
  return posthog.__loaded && getAnalyticsConsent() === 'granted';
}

/** No-op unless VITE_POSTHOG_ENABLED is 'true' and a key is set, so local dev stays quiet. */
function startPostHog(): void {
  const apiKey = import.meta.env.VITE_POSTHOG_KEY ?? '';
  if (import.meta.env.VITE_POSTHOG_ENABLED !== 'true' || !apiKey) return;
  if (!posthog.__loaded) {
    const config: Partial<PostHogConfig> = {
      api_host: import.meta.env.VITE_POSTHOG_HOST ?? 'https://eu.i.posthog.com',
      // In prod point VITE_POSTHOG_HOST at the Caddy relay (https://<domain>/ph-relay) so events bypass adblockers; ui_host keeps dashboard links pointing at PostHog.
      ui_host: import.meta.env.VITE_POSTHOG_UI_HOST ?? 'https://eu.posthog.com',
      // Cheaper, and keeps anonymous traffic out of the persons table.
      person_profiles: 'identified_only',
      // Autocapture only fires $pageview on initial load; PostHogPageviewTracker covers SPA navigations.
      capture_pageview: false,
      capture_pageleave: true,
      session_recording: {
        maskAllInputs: true,
      },
      capture_exceptions: true,
      // After a withdrawal clears PostHog's storage, its default must be off, not on.
      opt_out_capturing_by_default: true,
      opt_out_persistence_by_default: true,
    };
    posthog.init(apiKey, config);
  }
  posthog.opt_in_capturing({ captureEventName: false });
  posthog.register(superProperties);
}

function clearPostHogStorage(): void {
  const isPostHogKey = (name: string) => POSTHOG_PREFIXES.some((prefix) => name.startsWith(prefix));
  for (const store of [window.localStorage, window.sessionStorage]) {
    Object.keys(store)
      .filter(isPostHogKey)
      .forEach((key) => store.removeItem(key));
  }
  sessionStorage.removeItem(POSTHOG_IDENTIFIED_KEY);
  // A cookie is only removed with the domain it was set on, and PostHog sets it on the parent domain.
  const hostParts = window.location.hostname.split('.');
  const domains = [
    '',
    ...hostParts.map((_, i) => `; domain=.${hostParts.slice(i).join('.')}`).slice(0, -1),
  ];
  for (const cookie of document.cookie.split(';')) {
    const name = cookie.split('=')[0].trim();
    if (!isPostHogKey(name)) continue;
    for (const domain of domains) {
      document.cookie = `${name}=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/${domain}`;
    }
  }
}

function notifyConsent(): void {
  consentListeners.forEach((listener) => listener());
}

/** Starts PostHog at app start when this browser already gave Analytics consent. */
export function startAnalytics(): void {
  if (getAnalyticsConsent() === 'granted') startPostHog();
}

/** Accept: PostHog starts at once, and PostHogPageviewTracker captures the page on screen. */
export function grantAnalyticsConsent(): void {
  storage.set<AnalyticsConsent>('analytics-consent', 'granted');
  startPostHog();
  notifyConsent();
}

/** Reject, or withdraw an earlier Accept: PostHog stops and its browser storage is cleared. */
export function refuseAnalyticsConsent(): void {
  storage.set<AnalyticsConsent>('analytics-consent', 'denied');
  if (posthog.__loaded) {
    posthog.opt_out_capturing();
    posthog.reset();
  }
  clearPostHogStorage();
  notifyConsent();
}

/** Asks the consent banner to show again, so the visitor can change their choice. */
export function openCookieSettings(): void {
  settingsListeners.forEach((listener) => listener());
}

export function onCookieSettingsOpened(listener: Listener): () => void {
  settingsListeners.add(listener);
  return () => settingsListeners.delete(listener);
}

function subscribeConsent(listener: Listener): () => void {
  consentListeners.add(listener);
  return () => consentListeners.delete(listener);
}

export function useAnalyticsConsent(): AnalyticsConsent | null {
  return useSyncExternalStore(subscribeConsent, getAnalyticsConsent);
}

export function identifyUser(distinctId: string, properties?: Record<string, unknown>): void {
  if (!capturing()) return;
  posthog.identify(distinctId, properties);
}

export function resetPostHog(): void {
  if (!posthog.__loaded) return;
  posthog.reset();
  // reset() also forgets PostHog's opt-in, which by default means opted out.
  if (getAnalyticsConsent() === 'granted') posthog.opt_in_capturing({ captureEventName: false });
}

export function capturePageview(path: string): void {
  if (!capturing()) return;
  posthog.capture('$pageview', { $current_url: window.location.origin + path });
}

export function captureEvent(event: string, properties?: Record<string, unknown>): void {
  if (!capturing()) return;
  posthog.capture(event, properties);
}

/** Kept until PostHog starts, so properties registered before consent still reach it. */
export function registerSuperProperties(props: Record<string, unknown>): void {
  superProperties = { ...superProperties, ...props };
  if (capturing()) posthog.register(props);
}
