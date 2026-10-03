/** Full-page navigation (drops all in-memory state). No-op if already on `path`. */
export function hardRedirect(path: string): void {
  if (window.location.pathname !== path) {
    window.location.replace(path);
  }
}

/** Navigate to an external URL (e.g. Stripe Checkout) in the current tab. */
export function redirectTo(url: string): void {
  window.location.assign(url);
}
