import { useState, type FormEvent } from 'react';
import { X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { SubscribePrompt } from '@/features/billing/SubscribePrompt';
import { useSubscribed } from '@/features/billing/useSubscribed';
import { timeAgo } from '@/lib/relativeTime';
import type { InspirationAuthor } from '@/services/inspirationAuthorService';
import { useInspirationAuthors } from './useInspirationAuthors';

function ErrorBanner({ message }: { message: string }) {
  return (
    <div
      role="alert"
      className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 font-sans text-xs text-red-700 dark:text-red-300"
    >
      {message}
    </div>
  );
}

function fetchedLabel(author: InspirationAuthor): string {
  const posts = `${author.postCount} ${author.postCount === 1 ? 'post' : 'posts'}`;
  if (!author.lastFetchedAt) return posts;
  return `Fetched ${timeAgo(author.lastFetchedAt)} · ${posts}`;
}

function AddAuthorForm({
  isAdding,
  onAdd,
}: {
  isAdding: boolean;
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
    <form onSubmit={submit} className="flex gap-2">
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
        disabled={isAdding}
        className="min-w-0 flex-1"
      />
      <Button type="submit" disabled={isAdding || !handle.trim()} className="shrink-0">
        {isAdding ? 'Fetching posts…' : 'Add author'}
      </Button>
    </form>
  );
}

/**
 * On a phone the list is a row of chips holding only the handle, so it doesn't push the
 * writing area off the screen; from `md` up each author is a row with its fetch details.
 */
function AuthorList({
  authors,
  onRemove,
}: {
  authors: InspirationAuthor[];
  onRemove?: (handle: string) => void;
}) {
  return (
    <ul className="flex flex-wrap gap-2 md:flex-col md:flex-nowrap md:gap-0 md:divide-y md:divide-border md:rounded-lg md:border md:border-border">
      {authors.map((author) => (
        <li
          key={author.handle}
          className="flex h-10 items-center rounded-full border border-border pl-3 md:h-auto md:rounded-none md:border-0 md:py-2 md:pl-4 md:pr-2"
        >
          <div className="min-w-0 md:flex-1">
            <span className="font-sans text-sm font-medium text-foreground">@{author.handle}</span>
            <p className="hidden font-sans text-xs text-muted-foreground md:block">
              {fetchedLabel(author)}
            </p>
          </div>
          {onRemove ? (
            <button
              type="button"
              onClick={() => onRemove(author.handle)}
              aria-label={`Remove @${author.handle}`}
              className="ml-1 inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-full text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <X className="h-4 w-4" aria-hidden />
            </button>
          ) : (
            <span className="pr-3 md:pr-2" />
          )}
        </li>
      ))}
    </ul>
  );
}

export function InspirationAuthorsPanel() {
  const { subscribed } = useSubscribed();
  const { authors, loadFailed, isAdding, error, add, remove } = useInspirationAuthors();

  return (
    <section aria-labelledby="inspiration-authors-heading" className="space-y-4">
      <div className="space-y-1">
        <h2
          id="inspiration-authors-heading"
          className="font-sans text-base font-semibold text-foreground"
        >
          Inspiration authors
        </h2>
        <p className="font-sans text-sm text-muted-foreground">
          Up to three X accounts whose recent posts set how your posts sound, never what they say.
        </p>
      </div>

      {subscribed === false && (
        <SubscribePrompt
          message="Adding Inspiration authors needs a Subscription."
          source="home_inspiration_authors"
        />
      )}
      {subscribed === true && <AddAuthorForm isAdding={isAdding} onAdd={add} />}
      {error && <ErrorBanner message={error} />}

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
          onRemove={subscribed === true ? (handle) => void remove(handle) : undefined}
        />
      )}
    </section>
  );
}
