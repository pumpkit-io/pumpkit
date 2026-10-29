import type { Community, Destination, ScheduledPost } from '@/services/scheduledPostService';

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

export function communityUrl(id: string): string {
  return `https://x.com/i/communities/${id}`;
}

/** The Community ID in a pasted Community URL or bare ID, or null for anything else. */
export function communityIdFrom(pasted: string): string | null {
  const trimmed = pasted.trim();
  if (BARE_ID.test(trimmed)) return trimmed;
  return URL_PATTERN.exec(trimmed)?.[1] ?? null;
}

/** How far looking up the pasted Community's name has got; `id` is the Community looked up. */
export type CommunityLookup =
  | { state: 'none' }
  | { state: 'looking'; id: string }
  | { state: 'found'; id: string; name: string | null; url: string }
  | { state: 'missing'; id: string; message: string };

/**
 * What the field holds: the User's profile, a Community named by what they pasted, or one
 * they posted to before.
 */
export type DestinationDraft =
  | { kind: 'profile' }
  | {
      kind: 'community';
      pasted: string;
      shareWithFollowers: boolean;
      lookup: CommunityLookup;
    }
  | {
      kind: 'pastCommunity';
      community: Pick<Community, 'id' | 'name'>;
      shareWithFollowers: boolean;
    };

export const PROFILE_DRAFT: DestinationDraft = { kind: 'profile' };

/** Where a Scheduled post goes now, as the field holds it, so an edit or a retry starts there. */
export function destinationDraftOf({
  community,
  shareWithFollowers,
}: Pick<ScheduledPost, 'community' | 'shareWithFollowers'>): DestinationDraft {
  if (!community) return PROFILE_DRAFT;
  return {
    kind: 'community',
    pasted: community.url,
    shareWithFollowers,
    lookup: { state: 'found', ...community },
  };
}

/** The lookup a new paste needs: kept while it names the same Community, else a new one. */
export function lookupFor(pasted: string, current: CommunityLookup): CommunityLookup {
  const id = communityIdFrom(pasted);
  if (id === null) return { state: 'none' };
  if (current.state !== 'none' && current.id === id) return current;
  return { state: 'looking', id };
}

/** Where the draft sends a Scheduled post, or null until the pasted Community is looked up. */
export function destinationFrom(draft: DestinationDraft): Destination | null {
  if (draft.kind === 'profile') return PROFILE;
  if (draft.kind === 'pastCommunity') {
    return { community: draft.community, shareWithFollowers: draft.shareWithFollowers };
  }
  const { lookup } = draft;
  if (lookup.state !== 'found') return null;
  return {
    community: { id: lookup.id, name: lookup.name },
    shareWithFollowers: draft.shareWithFollowers,
  };
}
