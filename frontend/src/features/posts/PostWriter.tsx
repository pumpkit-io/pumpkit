import type { FormEvent, ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { CHOOSE_PLAN_PATH, trackChoosePlan } from '@/features/billing/choosePlan';
import { useSubscribed } from '@/features/billing/useSubscribed';
import { useInspirationAuthorsContext } from '@/features/inspirationAuthors/useInspirationAuthorsContext';
import { charCount } from '@/lib/characters';
import { BRIEF_MAX_CHARS, FORMAT_POST } from '@/services/postService';
import { ErrorBanner } from '@/components/ErrorBanner';
import { FeedbackForm } from './FeedbackForm';
import { FormatSelector } from './FormatSelector';
import { LengthCounter } from './LengthCounter';
import { LimitNotice } from '@/components/LimitNotice';
import { NumberedVersion } from './NumberedVersion';
import { usePostWriterContext } from './usePostWriterContext';

/** Where the write button goes when the User can't write yet, with the note beside it. */
function WriteGate({ action, note }: { action: ReactNode; note: string }) {
  return (
    <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
      {action}
      <p className="font-sans text-sm text-muted-foreground">{note}</p>
    </div>
  );
}

export function PostWriter() {
  const { subscribed } = useSubscribed();
  const { authors } = useInspirationAuthorsContext();
  const {
    post,
    isWriting,
    error,
    notice,
    start,
    addFeedback,
    brief,
    setBrief,
    format,
    setFormat,
    briefRef,
    newPost,
  } = usePostWriterContext();

  const noCorpus = authors !== null && !authors.some((a) => a.postCount > 0);
  const briefLength = charCount(brief);
  const overLimit = briefLength > BRIEF_MAX_CHARS;
  const canWrite = subscribed === true && !noCorpus && authors !== null && !overLimit;
  const typed = brief.trim();

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (canWrite && typed && !isWriting) void start(typed, format);
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
            <NumberedVersion key={version.number} version={version} />
          ))}
          <FeedbackForm
            key={post.id}
            subscribed={subscribed}
            isWriting={isWriting}
            error={error}
            notice={notice}
            latestFormat={post.versions[post.versions.length - 1]?.format ?? FORMAT_POST}
            onSend={addFeedback}
          />
        </div>
      ) : (
        <form onSubmit={submit} className="space-y-3">
          <div className="space-y-1.5">
            <label htmlFor="post-brief" className="font-sans text-sm font-medium text-foreground">
              Brief
            </label>
            <Textarea
              ref={briefRef}
              id="post-brief"
              value={brief}
              onChange={(e) => setBrief(e.target.value)}
              placeholder="What's the Post about, and what do you think about it?"
              rows={8}
              disabled={isWriting}
              className="min-h-[12rem] resize-y leading-relaxed"
            />
            <LengthCounter length={briefLength} max={BRIEF_MAX_CHARS} />
          </div>

          <FormatSelector value={format} onChange={setFormat} disabled={isWriting} />

          {error && (
            <ErrorBanner
              message={error}
              onRetry={typed ? () => void start(typed, format) : undefined}
            />
          )}
          {notice && <LimitNotice message={notice} />}

          {subscribed === false ? (
            <WriteGate
              action={
                <Button asChild className="h-10 shrink-0">
                  <Link to={CHOOSE_PLAN_PATH} onClick={() => trackChoosePlan('new_post_write')}>
                    Subscribe to write
                  </Link>
                </Button>
              }
              note="Your Drafts, schedule and Persona are kept."
            />
          ) : noCorpus ? (
            <WriteGate
              action={
                <Button asChild className="h-10 shrink-0">
                  <Link to="/persona">Set up your Persona</Link>
                </Button>
              }
              note="Add at least one Inspiration author first: Pumpkit writes in their style."
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
              {isWriting && (
                <p role="status" className="font-sans text-sm text-muted-foreground">
                  Writing your Post. This can take a minute or two.
                </p>
              )}
            </div>
          )}
        </form>
      )}
    </section>
  );
}
