import { useState, type FormEvent } from 'react';
import { RefreshCw, X } from 'lucide-react';
import { ErrorBanner } from '@/components/ErrorBanner';
import { LimitNotice } from '@/components/LimitNotice';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { UserAvatar } from '@/components/UserAvatar';
import { SubscribePrompt } from '@/features/billing/SubscribePrompt';
import { useSubscribed } from '@/features/billing/useSubscribed';
import { timeAgo } from '@/lib/relativeTime';
import { cn } from '@/lib/utils';
import {
  MAX_INSPIRATION_AUTHORS,
  type InspirationAuthor,
} from '@/services/inspirationAuthorService';
import { useInspirationAuthorsContext } from './useInspirationAuthorsContext';

function fetchedLabel(author: InspirationAuthor): string {
  const posts = `${author.postCount} ${author.postCount === 1 ? 'post' : 'posts'}`;
  if (!author.lastFetchedAt) return posts;
  return `Fetched ${timeAgo(author.lastFetchedAt)} · ${posts}`;
}

function AddAuthorForm({
  isAdding,
  full,
  onAdd,
}: {
  isAdding: boolean;
  /** Every place is taken, so the form waits for a Remove. */
  full: boolean;
  onAdd: (handle: string) => Promise<boolean>;
}) {
  const [handle, setHandle] = useState('');

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const typed = handle.trim();
    if (!typed) return;
    if (await onAdd(typed)) setHandle('');
  };

  return (
    <form onSubmit={submit} className="space-y-2">
      <div className="flex gap-2">
        <label htmlFor="inspiration-author-handle" className="sr-only">
          X handle
        </label>
        <Input
          id="inspiration-author-handle"
          value={handle}
          onChange={(e) => setHandle(e.target.value)}
          placeholder="@handle"
          autoComplete="off"
          autoCapitalize="none"
          spellCheck={false}
          disabled={isAdding || full}
          aria-describedby={full ? 'inspiration-authors-full' : undefined}
          className="min-w-0 flex-1"
        />
        <Button type="submit" disabled={isAdding || full || !handle.trim()} className="shrink-0">
          {isAdding ? 'Fetching posts…' : 'Add author'}
        </Button>
      </div>
      {full && (
        <p id="inspiration-authors-full" className="font-sans text-sm text-muted-foreground">
          All three places are taken. Remove an Inspiration author to add another.
        </p>
      )}
    </form>
  );
}

const ROW_ACTION =
  'inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-full text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-60';

interface AuthorActions {
  refreshing: string | null;
  onRefresh: (handle: string) => void;
  onRemove: (handle: string) => void;
}

function AuthorList({
  authors,
  actions,
}: {
  authors: InspirationAuthor[];
  actions?: AuthorActions;
}) {
  return (
    <ul className="divide-y divide-border rounded-lg border border-border">
      {authors.map((author) => (
        <li key={author.handle} className="flex items-center gap-3 py-2 pl-4 pr-2">
          <UserAvatar
            name={author.handle}
            avatarUrl={author.photoUrl}
            className="h-8 w-8 text-xs"
          />
          <div className="min-w-0 flex-1">
            <p className="truncate font-sans text-sm font-medium text-foreground">
              @{author.handle}
            </p>
            <p className="font-sans text-xs text-muted-foreground">{fetchedLabel(author)}</p>
          </div>
          {actions && (
            <div className="flex shrink-0">
              <button
                type="button"
                onClick={() => actions.onRefresh(author.handle)}
                disabled={actions.refreshing !== null}
                aria-label={
                  actions.refreshing === author.handle
                    ? `Refreshing @${author.handle}`
                    : `Refresh @${author.handle}`
                }
                title="Fetch the latest posts"
                className={ROW_ACTION}
              >
                <RefreshCw
                  className={`h-4 w-4 ${actions.refreshing === author.handle ? 'animate-spin motion-reduce:animate-none' : ''}`}
                  aria-hidden
                />
              </button>
              <button
                type="button"
                onClick={() => actions.onRemove(author.handle)}
                aria-label={`Remove @${author.handle}`}
                className={ROW_ACTION}
              >
                <X className="h-4 w-4" aria-hidden />
              </button>
            </div>
          )}
        </li>
      ))}
    </ul>
  );
}

/** One marker per place in the Persona, filled for each one taken. */
function PlacesTaken({ taken }: { taken: number }) {
  return (
    <div
      role="img"
      aria-label={`${taken} of ${MAX_INSPIRATION_AUTHORS} places taken`}
      className="flex items-center gap-1.5"
    >
      {Array.from({ length: MAX_INSPIRATION_AUTHORS }, (_, i) => (
        <span
          key={i}
          className={cn(
            'h-1.5 w-8 rounded-full',
            i < taken ? 'bg-primary' : 'bg-muted-foreground/25',
          )}
        />
      ))}
    </div>
  );
}

export function InspirationAuthorsPanel() {
  const { subscribed } = useSubscribed();
  const { authors, loadFailed, isAdding, refreshing, error, notice, add, refresh, remove } =
    useInspirationAuthorsContext();

  return (
    <section aria-labelledby="inspiration-authors-heading" className="space-y-5">
      <div className="flex items-start justify-between gap-4">
        <div className="space-y-1">
          <h2
            id="inspiration-authors-heading"
            className="font-sans text-xl font-semibold tracking-[-0.015em] text-foreground"
          >
            How your posts sound
          </h2>
          <p className="font-sans text-sm text-muted-foreground">
            Up to three X accounts, your Inspiration authors. Their recent posts set how your posts
            sound, never what they say.
          </p>
        </div>
        {authors !== null && <PlacesTaken taken={authors.length} />}
      </div>

      {subscribed === false && (
        <SubscribePrompt
          message="Adding Inspiration authors needs a Subscription."
          source="persona_inspiration_authors"
        />
      )}
      {subscribed === true && (
        <AddAuthorForm
          isAdding={isAdding}
          full={(authors?.length ?? 0) >= MAX_INSPIRATION_AUTHORS}
          onAdd={add}
        />
      )}
      {error && <ErrorBanner message={error} />}
      {notice && <LimitNotice message={notice} />}

      {loadFailed ? (
        <ErrorBanner message="Couldn't load your Inspiration authors. Reload the page to try again." />
      ) : authors === null ? (
        <p role="status" className="font-sans text-sm text-muted-foreground">
          Loading your Inspiration authors…
        </p>
      ) : authors.length === 0 ? (
        <p className="font-sans text-sm text-muted-foreground">
          No Inspiration authors yet.
          {subscribed === true && ' Add an X handle to set the style of your posts.'}
        </p>
      ) : (
        <AuthorList
          authors={authors}
          actions={
            subscribed === true
              ? {
                  refreshing,
                  onRefresh: (handle) => void refresh(handle),
                  onRemove: (handle) => void remove(handle),
                }
              : undefined
          }
        />
      )}
    </section>
  );
}
