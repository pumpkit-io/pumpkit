import { OAUTH_CONSENT_PATH } from './oauthConsentPath';
import { savedReturn } from './savedReturn';

/** Only an internal path to a consent request. */
function isResumable(path: string): boolean {
  if (!path.startsWith('/') || path.startsWith('//')) return false;
  return path.startsWith(`${OAUTH_CONSENT_PATH}?`);
}

/**
 * The consent page to resume after sign-in in the same browser, including an X authorization
 * that was cancelled and retried. A successful sign-in consumes the destination once.
 */
export const returnTo = savedReturn('return-to', isResumable);
