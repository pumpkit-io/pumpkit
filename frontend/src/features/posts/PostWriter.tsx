import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { useInspirationAuthorsContext } from '@/features/inspirationAuthors/useInspirationAuthorsContext';
import { track } from '@/lib/analytics';
import { BRIEF_MAX_CHARS, FORMAT_POST, postService, type Format } from '@/services/postService';
import { ErrorBanner } from '@/components/ErrorBanner';
import { Composer } from './Composer';
import { LimitNotice } from '@/components/LimitNotice';
import { isRefusal, useWritingFailure } from './useWritingFailure';

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
        fail(e, "Couldn't write the post. Try again.");
      } finally {
        if (mounted.current) setIsWriting(false);
      }
    },
    [clear, fail, navigate],
  );

  return { start, isWriting, error, notice, clear };
}

/** The line and the composer: a Brief and its Format, sent with the arrow or ⌘Enter. */
export function PostWriter() {
  const { authors } = useInspirationAuthorsContext();
  const { start, isWriting, error, notice, clear } = useStartPost();
  const [brief, setBrief] = useState('');
  const [format, setFormat] = useState<Format>(FORMAT_POST);
  const briefRef = useRef<HTMLTextAreaElement>(null);
  const { key } = useLocation();
  const shownKey = useRef(key);

  // New post navigates to /new even from /new, so a new location empties the composer, unless
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
  const typed = brief.trim();
  const send = () => void start(typed, format);

  const gate = noCorpus ? (
    <Button asChild variant="solid" className="h-10 shrink-0">
      <Link to="/persona">Set up your persona</Link>
    </Button>
  ) : undefined;

  return (
    <section aria-labelledby="new-post-line" className="space-y-3">
      <h2
        id="new-post-line"
        className="pb-1.5 font-sans text-2xl/[30px] font-semibold tracking-[-0.015em] text-foreground"
      >
        What&apos;s the post about?
      </h2>
      <Composer
        ref={briefRef}
        autoFocus
        label="Brief"
        placeholder="Write a new post about…"
        value={brief}
        onChange={setBrief}
        format={format}
        onFormatChange={setFormat}
        maxLength={BRIEF_MAX_CHARS}
        sendLabel="Write the post"
        onSend={send}
        isWriting={isWriting}
        sendDisabled={authors === null}
        gate={gate}
      />
      {isWriting && (
        <p role="status" className="font-sans text-[13px] text-muted-foreground">
          Writing your post. This takes a minute or two.
        </p>
      )}
      {error && <ErrorBanner message={error} onRetry={typed ? send : undefined} />}
      {notice && <LimitNotice message={notice} />}
    </section>
  );
}
