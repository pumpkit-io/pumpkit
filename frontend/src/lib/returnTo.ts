import { OAUTH_CONSENT_PATH } from './oauthConsentPath';
import { savedReturn } from './savedReturn';

/** Only an internal path to a consent request. */
function isResumable(path: string): boolean {
  if (!path.startsWith('/') || path.startsWith('//')) return false;
  return path.startsWith(`${OAUTH_CONSENT_PATH}?`);
}

/**
 * The page to land on after sign-in (pathname and search), so it survives Google's redirect and a
 * Magic link opened in the same browser. A Magic link opened on another device lands on New post.
 */
export const returnTo = savedReturn('return-to', isResumable);
