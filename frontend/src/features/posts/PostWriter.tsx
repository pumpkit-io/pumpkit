import { useCallback, useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { useBilling } from '@/features/billing/useBilling';
import { useSubscribed } from '@/features/billing/useSubscribed';
import { useInspirationAuthorsContext } from '@/features/inspirationAuthors/useInspirationAuthorsContext';
import { track } from '@/lib/analytics';
import { charCount } from '@/lib/characters';
import { BRIEF_MAX_CHARS, FORMAT_POST, postService, type Format } from '@/services/postService';
import { ErrorBanner } from '@/components/ErrorBanner';
import { FormatSelector } from './FormatSelector';
import { LengthCounter } from './LengthCounter';
import { LimitNotice } from '@/components/LimitNotice';
import { isRefusal, useWritingFailure } from './useWritingFailure';

/** Where the write button goes when the User can't write yet, with the note beside it. */
function WriteGate({ action, note }: { action: ReactNode; note: string }) {
  return (
    <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
      {action}
      <p className="font-sans text-sm text-muted-foreground">{note}</p>
    </div>
  );
}

/**
 * Starts a Post from a Brief and goes to its page once the first Version is written. On a
 * failure it stays, with the Brief kept, so trying again is one click.
 */
function useStartPost() {
  const navigate = useNavigate();
  const [isWriting, setIsWriting] = useState(false);
  const { error, notice, fail, clear } = useWritingFailure();
  // A User who leaves New post while it writes is not pulled back: the Post is kept under Posts.
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  /** Every call starts a new Post, a retry after a failure included. */
  const start = useCallback(
    async (brief: string, format: Format) => {
      setIsWriting(true);
      clear();
      track('post_version_requested', { kind: 'brief' });
      try {
        const post = await postService.start(brief, format);
        if (mounted.current) navigate(`/posts/${post.id}`);
      } catch (e) {
        if (!isRefusal(e)) track('post_version_failed', { kind: 'brief' });
        fail(e, "Couldn't write the Post. Please try again.");
      } finally {
        if (mounted.current) setIsWriting(false);
      }
    },
    [clear, fail, navigate],
  );

  return { start, isWriting, error, notice, clear };
}

/** The Brief and the Format, then "Write the Post". */
export function PostWriter() {
  const { subscribed } = useSubscribed();
  const billing = useBilling();
  const { authors } = useInspirationAuthorsContext();
  const { start, isWriting, error, notice, clear } = useStartPost();
  const [brief, setBrief] = useState('');
  const [format, setFormat] = useState<Format>(FORMAT_POST);
  const briefRef = useRef<HTMLTextAreaElement>(null);
  const { key } = useLocation();
  const shownKey = useRef(key);

  // New post navigates to /new even from /new, so a new location empties the form, unless
  // it is writing: then the Brief stays until the Post's page opens.
  useEffect(() => {
    if (shownKey.current === key) return;
    shownKey.current = key;
    if (isWriting) return;
    setBrief('');
    setFormat(FORMAT_POST);
    clear();
    briefRef.current?.focus();
  }, [key, isWriting, clear]);

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
      </div>

      <form onSubmit={submit} className="space-y-3">
        <div className="space-y-1.5">
          <label htmlFor="post-brief" className="font-sans text-sm font-medium text-foreground">
            Brief
          </label>
          <Textarea
            ref={briefRef}
            autoFocus
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
              <Button
                type="button"
                className="h-10 shrink-0"
                onClick={() => billing.open('new_post_write')}
              >
                Subscribe to write
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
    </section>
  );
}
