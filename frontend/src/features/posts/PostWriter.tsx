import { useState, type FormEvent } from 'react';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { SubscribePrompt } from '@/features/billing/SubscribePrompt';
import { useSubscribed } from '@/features/billing/useSubscribed';
import { useInspirationAuthorsContext } from '@/features/inspirationAuthors/useInspirationAuthorsContext';
import { charCount } from '@/lib/characters';
import { BRIEF_MAX_CHARS } from '@/services/postService';
import { ErrorBanner } from '@/components/ErrorBanner';
import { FeedbackForm } from './FeedbackForm';
import { LengthCounter } from './LengthCounter';
import { LimitNotice } from '@/components/LimitNotice';
import { NumberedVersion } from './NumberedVersion';
import { usePostWriter } from './usePostWriter';

export function PostWriter() {
  const { subscribed } = useSubscribed();
  const { authors } = useInspirationAuthorsContext();
  const { post, isWriting, error, notice, start, addFeedback, clear } = usePostWriter();
  const [brief, setBrief] = useState('');

  const noCorpus = authors !== null && !authors.some((a) => a.postCount > 0);
  const briefLength = charCount(brief);
  const overLimit = briefLength > BRIEF_MAX_CHARS;
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
            <NumberedVersion key={version.number} version={version} />
          ))}
          <FeedbackForm
            key={post.id}
            subscribed={subscribed}
            isWriting={isWriting}
            error={error}
            notice={notice}
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

          {error && (
            <ErrorBanner message={error} onRetry={typed ? () => void start(typed) : undefined} />
          )}
          {notice && <LimitNotice message={notice} />}

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
