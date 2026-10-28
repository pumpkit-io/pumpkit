import { useEffect, useRef } from 'react';
import { track } from '@/lib/analytics';
import { errorMessage, errorStatus } from '@/services/apiErrors';
import { scheduledPostService } from '@/services/scheduledPostService';
import { communityUrl, type CommunityLookup, type DestinationDraft } from './communities';

/**
 * Looks up the Community the draft names whenever it names a new one, and hands the draft back
 * with the outcome, unless the User has pasted something else in the meantime.
 */
export function useCommunityLookup(
  value: DestinationDraft,
  onChange: (value: DestinationDraft) => void,
) {
  const latest = useRef({ value, onChange });
  latest.current = { value, onChange };
  const lookingFor =
    value.kind === 'community' && value.lookup.state === 'looking' ? value.lookup.id : null;

  useEffect(() => {
    if (lookingFor === null) return;
    const settle = (lookup: CommunityLookup) => {
      const { value: current, onChange: change } = latest.current;
      if (current.kind !== 'community' || current.lookup.state !== 'looking') return;
      if (current.lookup.id !== lookingFor) return;
      change({ ...current, lookup });
    };
    scheduledPostService.lookUpCommunity(lookingFor).then(
      (community) => {
        track('community_looked_up', { found: true, named: community.name !== null });
        settle({ state: 'found', ...community });
      },
      (error: unknown) => {
        if (errorStatus(error) === 404) {
          track('community_looked_up', { found: false });
          settle({
            state: 'missing',
            id: lookingFor,
            message: errorMessage(error, 'X has no Community with that ID.'),
          });
          return;
        }
        // The name is only a label: without it the Community still takes posts, shown by its ID.
        settle({
          state: 'found',
          id: lookingFor,
          name: null,
          url: communityUrl(lookingFor),
        });
      },
    );
  }, [lookingFor]);
}
