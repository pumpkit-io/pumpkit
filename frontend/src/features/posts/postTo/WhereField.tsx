import { useEffect, useId, useState } from 'react';
import { Input } from '@/components/ui/input';
import {
  communityIdFrom,
  lookupFor,
  NOT_A_COMMUNITY,
  PROFILE_DRAFT,
  type DestinationDraft,
} from '@/features/scheduledPosts/communities';
import { InTheCommunity } from '@/features/scheduledPosts/InTheCommunity';
import { useCommunityLookup } from '@/features/scheduledPosts/useCommunityLookup';
import { usePastCommunities } from '@/features/scheduledPosts/usePastCommunities';
import type { Community } from '@/services/scheduledPostService';
import { Segmented } from './Segmented';

const ADD = 'add';

const PASTING: DestinationDraft = {
  kind: 'community',
  pasted: '',
  shareWithFollowers: true,
  lookup: { state: 'none' },
};

function pastDraft(community: Pick<Community, 'id' | 'name'>): DestinationDraft {
  return {
    kind: 'pastCommunity',
    community: { id: community.id, name: community.name },
    shareWithFollowers: true,
  };
}

const LABEL = 'block font-sans text-sm font-medium text-foreground';

/**
 * My profile, or a Community: one the User posted to before, picked from a list, or one added by
 * pasting its URL. A Community starts shared with followers.
 */
export function WhereField({
  value,
  onChange,
  disabled,
}: {
  value: DestinationDraft;
  onChange: (value: DestinationDraft) => void;
  disabled?: boolean;
}) {
  const id = useId();
  const past = usePastCommunities();
  // Set once the User picks "Add one by URL", so the past list arriving late doesn't override it.
  const [adding, setAdding] = useState(false);
  useCommunityLookup(value, onChange);

  const first = past[0];
  const untouchedPaste = value.kind === 'community' && value.pasted === '' && !adding;
  useEffect(() => {
    if (untouchedPaste && first) onChange(pastDraft(first));
  }, [untouchedPaste, first, onChange]);

  const choose = (kind: 'profile' | 'community') => {
    setAdding(false);
    if (kind === 'profile') onChange(PROFILE_DRAFT);
    else onChange(first ? pastDraft(first) : PASTING);
  };

  const pick = (selected: string) => {
    const community = past.find((c) => c.id === selected);
    setAdding(!community);
    onChange(community ? pastDraft(community) : PASTING);
  };

  return (
    <div className="space-y-3">
      <Segmented
        legend="Where"
        options={[
          { value: 'profile', label: 'My profile' },
          { value: 'community', label: 'Community' },
        ]}
        value={value.kind === 'profile' ? 'profile' : 'community'}
        onChange={choose}
        disabled={disabled}
      />
      {value.kind !== 'profile' && (
        <div className="space-y-3 rounded-lg border border-border p-3">
          {past.length > 0 && (
            <div className="space-y-1.5">
              <label htmlFor={`${id}-past`} className={LABEL}>
                Which Community
              </label>
              <select
                id={`${id}-past`}
                value={value.kind === 'pastCommunity' ? value.community.id : ADD}
                onChange={(e) => pick(e.target.value)}
                disabled={disabled}
                className="flex h-10 w-full rounded-lg border border-input bg-card px-3 py-2 font-sans text-sm text-foreground ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {past.map((community) => (
                  <option key={community.id} value={community.id}>
                    {community.name ?? community.id}
                  </option>
                ))}
                <option value={ADD}>Add one by URL</option>
              </select>
            </div>
          )}
          {value.kind === 'community' && (
            <PastedCommunity id={id} value={value} onChange={onChange} disabled={disabled} />
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
        </div>
      )}
    </div>
  );
}

function PastedCommunity({
  id,
  value,
  onChange,
  disabled,
}: {
  id: string;
  value: Extract<DestinationDraft, { kind: 'community' }>;
  onChange: (value: DestinationDraft) => void;
  disabled?: boolean;
}) {
  const { lookup } = value;
  const unreadable = value.pasted.trim() !== '' && !communityIdFrom(value.pasted);
  const problem = unreadable ? NOT_A_COMMUNITY : lookup.state === 'missing' ? lookup.message : null;
  return (
    <div className="space-y-1.5">
      <label htmlFor={`${id}-community`} className={LABEL}>
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
        <p id={`${id}-problem`} className="font-sans text-xs text-destructive">
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
  );
}
