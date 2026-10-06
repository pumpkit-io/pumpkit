import { useState, type FormEvent } from 'react';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { SubscribePrompt } from '@/features/billing/SubscribePrompt';
import { useSubscribed } from '@/features/billing/useSubscribed';
import { useInspirationAuthorsContext } from '@/features/inspirationAuthors/useInspirationAuthorsContext';
import { cn } from '@/lib/utils';
import { BRIEF_MAX_CHARS } from '@/services/postService';
import { usePostWriter } from './usePostWriter';
import { VersionView } from './VersionView';

// The limit guards against abuse, so the counter stays out of the way until a Brief nears it.
const COUNTER_FROM = BRIEF_MAX_CHARS - 10_000;

const formatCount = (n: number) => n.toLocaleString('en-US');

function BriefCounter({ length }: { length: number }) {
  if (length < COUNTER_FROM) return null;
  const over = length - BRIEF_MAX_CHARS;
  return (
    <p
      className={cn(
        'font-sans text-xs tabular-nums',
        over > 0 ? 'font-medium text-red-700 dark:text-red-300' : 'text-muted-foreground',
      )}
    >
      {over > 0
        ? `${formatCount(over)} characters over the ${formatCount(BRIEF_MAX_CHARS)} limit`
        : `${formatCount(length)} / ${formatCount(BRIEF_MAX_CHARS)} characters`}
    </p>
  );
}

function ErrorBanner({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div
      role="alert"
      className="flex flex-col gap-2 rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 font-sans text-xs text-red-700 dark:text-red-300 sm:flex-row sm:items-center sm:justify-between"
    >
      <span>{message}</span>
      {onRetry && (
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="h-10 shrink-0"
          onClick={onRetry}
        >
          Try again
        </Button>
      )}
    </div>
  );
}

export function PostWriter() {
  const { subscribed } = useSubscribed();
  const { authors } = useInspirationAuthorsContext();
  const { post, isWriting, error, start, clear } = usePostWriter();
  const [brief, setBrief] = useState('');

  const noCorpus = authors !== null && !authors.some((a) => a.postCount > 0);
  const overLimit = brief.length > BRIEF_MAX_CHARS;
  const canWrite = subscribed === true && !noCorpus && authors !== null && !overLimit;
  const typed = brief.trim();

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (canWrite && typed && !isWriting) void start(typed);
  };

  const newPost = () => {
    clear();
    setBrief('');
  };

  return (
    <section aria-labelledby="write-a-post-heading" className="space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div className="space-y-1">
          <h2
            id="write-a-post-heading"
            className="font-sans text-base font-semibold text-foreground"
          >
            Write a Post
          </h2>
          <p className="font-sans text-sm text-muted-foreground">
            Say what the Post is about and what you think. Rambling is fine: Pumpkit finds the point
            and writes it in your Inspiration authors&apos; style.
          </p>
        </div>
        {post && (
          <Button variant="outline" className="h-10 shrink-0" onClick={newPost}>
            New Post
          </Button>
        )}
      </div>

      {post ? (
        <div className="space-y-6">
          <div className="space-y-1">
            <p className="font-sans text-xs font-medium text-muted-foreground">Your Brief</p>
            <p className="max-h-40 overflow-y-auto whitespace-pre-wrap break-words border-l-2 border-border pl-3 font-sans text-sm text-muted-foreground">
              {post.brief}
            </p>
          </div>
          {post.versions.map((version) => (
            <VersionView key={version.number} version={version} />
          ))}
        </div>
      ) : (
        <form onSubmit={submit} className="space-y-3">
          <div className="space-y-1.5">
            <label htmlFor="post-brief" className="font-sans text-sm font-medium text-foreground">
              Brief
            </label>
            <Textarea
              id="post-brief"
              value={brief}
              onChange={(e) => setBrief(e.target.value)}
              placeholder="What's the Post about, and what do you think about it?"
              rows={8}
              disabled={isWriting}
              className="min-h-[12rem] resize-y leading-relaxed"
            />
            <BriefCounter length={brief.length} />
          </div>

          {error && (
            <ErrorBanner message={error} onRetry={typed ? () => void start(typed) : undefined} />
          )}

          {subscribed === false ? (
            <SubscribePrompt
              message="Writing Posts needs a Subscription."
              source="home_write_post"
            />
          ) : (
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
              <Button
                type="submit"
                className="h-10 shrink-0"
                disabled={!canWrite || !typed || isWriting}
              >
                {isWriting ? 'Writing…' : 'Write the Post'}
              </Button>
              {isWriting ? (
                <p role="status" className="font-sans text-sm text-muted-foreground">
                  Writing your Post. This can take a minute or two.
                </p>
              ) : (
                noCorpus && (
                  <p className="font-sans text-sm text-muted-foreground">
                    Add an Inspiration author to write a Post.
                  </p>
                )
              )}
            </div>
          )}
        </form>
      )}
    </section>
  );
}
