import { useId } from 'react';
import { Input } from '@/components/ui/input';
import {
  communityIdFrom,
  NOT_A_COMMUNITY,
  PROFILE_DRAFT,
  type DestinationDraft,
} from './communities';

/**
 * Where a Scheduled post goes: "My profile", or a Community named by pasting its URL or ID.
 * While a Community is chosen, an "Also share with followers" checkbox shows, checked each
 * time one is picked.
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
  const unreadable =
    value.kind === 'community' && value.pasted.trim() !== '' && !communityIdFrom(value.pasted);

  return (
    <div className="space-y-3">
      <div className="space-y-1.5">
        <label htmlFor={`${id}-to`} className="block font-sans text-sm font-medium text-foreground">
          Post to
        </label>
        <select
          id={`${id}-to`}
          value={value.kind}
          onChange={(e) =>
            onChange(
              e.target.value === 'community'
                ? { kind: 'community', pasted: '', shareWithFollowers: true }
                : PROFILE_DRAFT,
            )
          }
          disabled={disabled}
          className="flex h-10 w-full rounded-lg border border-muted-foreground bg-background px-3 py-2 font-sans text-sm text-foreground ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 sm:w-64"
        >
          <option value="profile">My profile</option>
          <option value="community">A Community</option>
        </select>
      </div>
      {value.kind === 'community' && (
        <>
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
              onChange={(e) => onChange({ ...value, pasted: e.target.value })}
              placeholder="https://x.com/i/communities/…"
              aria-invalid={unreadable}
              aria-describedby={unreadable ? `${id}-unreadable` : undefined}
              disabled={disabled}
              autoComplete="off"
              spellCheck={false}
            />
            {unreadable && (
              <p
                id={`${id}-unreadable`}
                className="font-sans text-xs text-red-700 dark:text-red-300"
              >
                {NOT_A_COMMUNITY}
              </p>
            )}
          </div>
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
