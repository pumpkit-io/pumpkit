import type { Destination } from '@/services/scheduledPostService';

/** Where a Scheduled post goes unless the User picks a Community. */
export const PROFILE: Destination = { community: null, shareWithFollowers: false };

/** Mirrors the backend's message for text that names no Community. */
export const NOT_A_COMMUNITY =
  "That isn't a Community. Paste its URL from X, like https://x.com/i/communities/123, or its ID.";

// X's pattern for a Community ID; mirrors backend/src/pumpkit/scheduling/communities.py.
const ID = '[0-9]{1,19}';
const BARE_ID = new RegExp(`^${ID}$`);
const URL_PATTERN = new RegExp(
  String.raw`^(?:https?://)?(?:www\.)?(?:x|twitter)\.com/i/communities/(${ID})/?(?:\?\S*)?$`,
  'i',
);

/** The Community ID in a pasted Community URL or bare ID, or null for anything else. */
export function communityIdFrom(pasted: string): string | null {
  const trimmed = pasted.trim();
  if (BARE_ID.test(trimmed)) return trimmed;
  return URL_PATTERN.exec(trimmed)?.[1] ?? null;
}

/** What the field holds: the User's profile, or a Community named by what they pasted. */
export type DestinationDraft =
  { kind: 'profile' } | { kind: 'community'; pasted: string; shareWithFollowers: boolean };

export const PROFILE_DRAFT: DestinationDraft = { kind: 'profile' };

/** Where the draft sends a Scheduled post, or null while the paste names no Community. */
export function destinationFrom(draft: DestinationDraft): Destination | null {
  if (draft.kind === 'profile') return PROFILE;
  const id = communityIdFrom(draft.pasted);
  if (id === null) return null;
  return { community: { id, name: null }, shareWithFollowers: draft.shareWithFollowers };
}
