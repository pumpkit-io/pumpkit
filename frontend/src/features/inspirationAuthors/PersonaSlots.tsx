import { Loader2, Plus, RefreshCw, X } from 'lucide-react';
import { UserAvatar } from '@/components/UserAvatar';
import { timeAgo } from '@/lib/relativeTime';
import { cn } from '@/lib/utils';
import { xPhotoAt } from '@/lib/xPhoto';
import {
  MAX_INSPIRATION_AUTHORS,
  type InspirationAuthor,
} from '@/services/inspirationAuthorService';

const SLOT_PHOTO_PX = 80;
const SLOT =
  'relative flex min-h-40 flex-col items-center rounded-xl px-2 pb-3 pt-12 text-center sm:min-h-48 sm:px-3';
const SLOT_ACTION =
  'absolute top-1 inline-flex h-10 w-10 items-center justify-center rounded-full text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-60';

interface RefreshActions {
  refreshing: string | null;
  onRefresh: (handle: string) => void;
}

interface PersonaSlotsProps {
  authors: InspirationAuthor[];
  /** The handle being added, shown in the next slot while its posts are read. */
  adding: string | null;
  onRemove: (handle: string) => void;
  /** An empty slot was pressed: the caller moves focus to its search. */
  onChooseEmpty: () => void;
  /** Shows when each author was last fetched, with a refresh button. */
  refresh?: RefreshActions;
}

/** The three places of a Persona, each filling with an author's photo, name and @handle. */
export function PersonaSlots({
  authors,
  adding,
  onRemove,
  onChooseEmpty,
  refresh,
}: PersonaSlotsProps) {
  const fetching = adding !== null && !authors.some((a) => a.handle === adding) ? adding : null;
  const taken = authors.length + (fetching ? 1 : 0);
  const empty = Math.max(0, MAX_INSPIRATION_AUTHORS - taken);

  return (
    <ul
      aria-label={`${authors.length} of ${MAX_INSPIRATION_AUTHORS} places taken`}
      className="grid grid-cols-3 gap-2 sm:gap-3"
    >
      {authors.map((author) => (
        <li
          key={author.handle}
          className={cn(
            SLOT,
            'border border-border bg-card shadow-raised motion-safe:animate-in motion-safe:fade-in motion-safe:zoom-in-95',
          )}
        >
          {refresh && (
            <button
              type="button"
              onClick={() => refresh.onRefresh(author.handle)}
              disabled={refresh.refreshing !== null}
              aria-label={
                refresh.refreshing === author.handle
                  ? `Refreshing @${author.handle}`
                  : `Refresh @${author.handle}`
              }
              title="Fetch the latest posts"
              className={cn(SLOT_ACTION, 'left-1')}
            >
              <RefreshCw
                aria-hidden
                className={cn(
                  'h-4 w-4',
                  refresh.refreshing === author.handle && 'animate-spin motion-reduce:animate-none',
                )}
              />
            </button>
          )}
          <button
            type="button"
            onClick={() => onRemove(author.handle)}
            aria-label={`Remove @${author.handle}`}
            className={cn(SLOT_ACTION, 'right-1')}
          >
            <X aria-hidden className="h-4 w-4" />
          </button>
          <UserAvatar
            name={author.name ?? author.handle}
            avatarUrl={xPhotoAt(author.photoUrl, SLOT_PHOTO_PX)}
            className="h-14 w-14 text-lg ring-2 ring-card sm:h-20 sm:w-20 sm:text-2xl"
          />
          <div className="mt-3 w-full min-w-0 space-y-0.5 font-sans">
            {author.name && (
              <p className="truncate text-sm font-semibold text-foreground">{author.name}</p>
            )}
            <p
              className={cn(
                'truncate text-xs',
                author.name ? 'text-muted-foreground' : 'font-semibold text-foreground',
              )}
            >
              @{author.handle}
            </p>
            {refresh && (
              <p className="pt-1 text-xs text-muted-foreground">{fetchedLabel(author)}</p>
            )}
          </div>
        </li>
      ))}
      {fetching && (
        <li className={cn(SLOT, 'justify-center border border-border bg-card pt-3')}>
          <Loader2
            aria-hidden
            className="h-6 w-6 animate-spin text-primary motion-reduce:animate-none"
          />
          <p className="mt-3 w-full break-words font-sans text-xs text-muted-foreground">
            Reading @{fetching}'s posts…
          </p>
        </li>
      )}
      {Array.from({ length: empty }, (_, i) => (
        <li key={`empty-${i}`} className="flex">
          <button
            type="button"
            onClick={onChooseEmpty}
            aria-label="Add an author"
            className={cn(
              SLOT,
              'w-full justify-center border border-dashed border-muted-foreground/80 pt-3 text-muted-foreground hover:border-primary hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
            )}
          >
            <Plus aria-hidden className="h-6 w-6" />
          </button>
        </li>
      ))}
    </ul>
  );
}

function fetchedLabel(author: InspirationAuthor): string {
  const posts = `${author.postCount} ${author.postCount === 1 ? 'post' : 'posts'}`;
  if (!author.lastFetchedAt) return posts;
  return `Fetched ${timeAgo(author.lastFetchedAt)} · ${posts}`;
}
