import { useEffect, useId, useRef } from 'react';
import { Input } from '@/components/ui/input';
import { track } from '@/lib/analytics';
import { errorMessage, errorStatus } from '@/services/apiErrors';
import { scheduledPostService, type Community } from '@/services/scheduledPostService';
import {
  communityIdFrom,
  communityUrl,
  lookupFor,
  NOT_A_COMMUNITY,
  PROFILE_DRAFT,
  type CommunityLookup,
  type DestinationDraft,
} from './communities';
import { InTheCommunity } from './InTheCommunity';
import { usePastCommunities } from './usePastCommunities';

const PAST = 'past:';
const NOT_LOOKED_UP: CommunityLookup = { state: 'none' };

/**
 * Looks up the Community the draft names whenever it names a new one, and hands the draft back
 * with the outcome, unless the User has pasted something else in the meantime.
 */
function useCommunityLookup(value: DestinationDraft, onChange: (value: DestinationDraft) => void) {
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

/**
 * Where a Scheduled post goes: "My profile", a Community the User posted to before, or one
 * named by pasting its URL or ID. While a Community is chosen, an "Also share with followers"
 * checkbox shows, checked each time one is picked. A `pastCommunity` value missing from the
 * past list is offered among them all the same.
 */
export function DestinationField({
  value,
  onChange,
  disabled,
}: {
  value: DestinationDraft;
  onChange: (value: DestinationDraft) => void;
  disabled?: boolean;
}) {
  const id = useId();
  const loaded = usePastCommunities();
  const past =
    value.kind === 'pastCommunity' && !loaded.some((c) => c.id === value.community.id)
      ? [value.community, ...loaded]
      : loaded;
  useCommunityLookup(value, onChange);
  const unreadable =
    value.kind === 'community' && value.pasted.trim() !== '' && !communityIdFrom(value.pasted);
  const lookup = value.kind === 'community' ? value.lookup : NOT_LOOKED_UP;
  const problem = unreadable ? NOT_A_COMMUNITY : lookup.state === 'missing' ? lookup.message : null;

  return (
    <div className="space-y-3">
      <div className="space-y-1.5">
        <label htmlFor={`${id}-to`} className="block font-sans text-sm font-medium text-foreground">
          Post to
        </label>
        <select
          id={`${id}-to`}
          value={value.kind === 'pastCommunity' ? PAST + value.community.id : value.kind}
          onChange={(e) => onChange(draftFor(e.target.value, past))}
          disabled={disabled}
          className="flex h-10 w-full rounded-lg border border-muted-foreground bg-background px-3 py-2 font-sans text-sm text-foreground ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 sm:w-64"
        >
          <option value="profile">My profile</option>
          {past.map((community) => (
            <option key={community.id} value={PAST + community.id}>
              {community.name ?? community.id}
            </option>
          ))}
          <option value="community">{past.length ? 'Another Community' : 'A Community'}</option>
        </select>
      </div>
      {value.kind !== 'profile' && (
        <>
          {value.kind === 'community' && (
            <div className="space-y-1.5">
              <label
                htmlFor={`${id}-community`}
                className="block font-sans text-sm font-medium text-foreground"
              >
                Community URL or ID
              </label>
              <Input
                id={`${id}-community`}
                value={value.pasted}
                onChange={(e) =>
                  onChange({
                    ...value,
                    pasted: e.target.value,
                    lookup: lookupFor(e.target.value, value.lookup),
                  })
                }
                placeholder="https://x.com/i/communities/…"
                aria-invalid={problem !== null}
                aria-describedby={problem !== null ? `${id}-problem` : undefined}
                disabled={disabled}
                autoComplete="off"
                spellCheck={false}
              />
              {problem !== null && (
                <p
                  id={`${id}-problem`}
                  className="font-sans text-xs text-red-700 dark:text-red-300"
                >
                  {problem}
                </p>
              )}
              {lookup.state === 'looking' && (
                <p role="status" className="font-sans text-xs text-muted-foreground">
                  Looking up the Community…
                </p>
              )}
              {lookup.state === 'found' && (
                <p className="font-sans text-xs text-muted-foreground">
                  <InTheCommunity community={lookup} />
                </p>
              )}
            </div>
          )}
          <label className="flex cursor-pointer items-center gap-3 font-sans text-sm text-foreground">
            <input
              type="checkbox"
              checked={value.shareWithFollowers}
              onChange={(e) => onChange({ ...value, shareWithFollowers: e.target.checked })}
              disabled={disabled}
              className="h-4 w-4 shrink-0 cursor-pointer accent-primary"
            />
            Also share with followers
          </label>
        </>
      )}
    </div>
  );
}

function draftFor(selected: string, past: Pick<Community, 'id' | 'name'>[]): DestinationDraft {
  if (selected === 'community') {
    return { kind: 'community', pasted: '', shareWithFollowers: true, lookup: NOT_LOOKED_UP };
  }
  const community = past.find((c) => PAST + c.id === selected);
  if (!community) return PROFILE_DRAFT;
  return {
    kind: 'pastCommunity',
    community: { id: community.id, name: community.name },
    shareWithFollowers: true,
  };
}
