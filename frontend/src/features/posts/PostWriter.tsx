import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { useHasPositioning } from '@/features/positioning/useHasPositioning';
import { track } from '@/lib/analytics';
import { BRIEF_MAX_CHARS } from '@/services/postService';
import { briefPosts, briefService, splitIdeas, type Brief } from '@/services/briefService';
import { IdeasStep, type IdeasChoice } from '@/features/briefs/IdeasStep';
import { ErrorBanner } from '@/components/ErrorBanner';
import { Composer } from './Composer';
import { Notice } from '@/components/Notice';
import { AllowanceNotice } from '@/features/billing/AllowanceNotice';
import { LowUsageWarning } from '@/features/billing/LowUsageWarning';
import { useUsage } from '@/features/billing/useUsage';
import { isRefusal, useWritingFailure } from './useWritingFailure';

/**
 * Plans a Brief. With one Idea its Post is already being written, so it goes to the Post's page;
 * with several it shows them to pick from. On a failure it stays, with the Brief kept, so trying
 * again is one click.
 */
function usePlanBrief() {
  const navigate = useNavigate();
  const [isPlanning, setIsPlanning] = useState(false);
  const [ideasOf, setIdeasOf] = useState<Brief | null>(null);
  const [isStarting, setIsStarting] = useState(false);
  const { error, notice, allowanceUsedUp, fail, clear } = useWritingFailure();
  // A User who leaves New post while the Brief is planned is not pulled back to the Post.
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  /** Every call plans a new Brief, a retry after a failure included. */
  const plan = useCallback(
    async (text: string) => {
      setIsPlanning(true);
      clear();
      track('post_version_requested', { kind: 'brief' });
      try {
        const brief = await briefService.plan(text);
        const split = splitIdeas(brief).length;
        track('brief_planned', { split_ideas: split });
        if (!mounted.current) return;
        const [started] = briefPosts(brief);
        if (split === 0 && started) navigate(`/posts/${started.post.id}`);
        else setIdeasOf(brief);
      } catch (e) {
        if (!isRefusal(e)) track('post_version_failed', { kind: 'brief' });
        fail(e, "Couldn't plan the post. Try again.");
      } finally {
        if (mounted.current) setIsPlanning(false);
      }
    },
    [clear, fail, navigate],
  );

  /** Writes the Ideas picked: one Post opens its page, several open the Brief's. */
  const write = useCallback(
    async (brief: Brief, ideaIds: string[], choice: IdeasChoice) => {
      setIsStarting(true);
      clear();
      track('ideas_write_requested', { count: ideaIds.length, choice });
      try {
        const written = briefPosts(await briefService.write(brief.id, ideaIds));
        if (!mounted.current) return;
        const [only] = written;
        if (written.length === 1 && only) navigate(`/posts/${only.post.id}`);
        else navigate(`/briefs/${brief.id}`);
      } catch (e) {
        fail(e, "Couldn't start writing the posts. Try again.");
      } finally {
        if (mounted.current) setIsStarting(false);
      }
    },
    [clear, fail, navigate],
  );

  const editBrief = useCallback(() => {
    clear();
    setIdeasOf(null);
  }, [clear]);

  return {
    plan,
    write,
    editBrief,
    ideasOf,
    isPlanning,
    isStarting,
    error,
    notice,
    allowanceUsedUp,
  };
}

/**
 * The line and the composer: a Brief, sent with the arrow or ⌘Enter. The planner chooses a single
 * post or a thread, so a User who wants a thread asks for one in the Brief.
 */
export function PostWriter() {
  const hasPositioning = useHasPositioning();
  const {
    plan,
    write,
    editBrief,
    ideasOf,
    isPlanning,
    isStarting,
    error,
    notice,
    allowanceUsedUp,
  } = usePlanBrief();
  const { usage } = useUsage();
  const [brief, setBrief] = useState('');
  const briefRef = useRef<HTMLTextAreaElement>(null);
  const { key } = useLocation();
  const shownKey = useRef(key);

  // New post navigates to /new even from /new, so a new location empties the composer, unless
  // it is planning: then the Brief stays until the Post's page opens.
  useEffect(() => {
    if (shownKey.current === key) return;
    shownKey.current = key;
    if (isPlanning) return;
    setBrief('');
    editBrief();
    briefRef.current?.focus();
  }, [key, isPlanning, editBrief]);

  const typed = brief.trim();
  const send = () => void plan(typed);

  const failure = (
    <>
      {error && <ErrorBanner message={error} />}
      {notice && <Notice message={notice} />}
      {allowanceUsedUp && <AllowanceNotice refusal={allowanceUsedUp} />}
    </>
  );

  if (ideasOf)
    return (
      <IdeasStep
        brief={ideasOf}
        allowance={usage?.allowance}
        writing={isStarting}
        onWrite={(ideaIds, choice) => void write(ideasOf, ideaIds, choice)}
        onEditBrief={editBrief}
      >
        {failure}
      </IdeasStep>
    );

  const gate =
    hasPositioning === false ? (
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
        maxLength={BRIEF_MAX_CHARS}
        sendLabel="Write the post"
        onSend={send}
        isWriting={isPlanning}
        sendDisabled={hasPositioning === null}
        gate={gate}
      />
      {!allowanceUsedUp && <LowUsageWarning allowance={usage?.allowance} count="generations" />}
      {isPlanning && (
        <p role="status" className="font-sans text-[13px] text-muted-foreground">
          Reading your brief…
        </p>
      )}
      {error && <ErrorBanner message={error} onRetry={typed ? send : undefined} />}
      {notice && <Notice message={notice} />}
      {allowanceUsedUp && <AllowanceNotice refusal={allowanceUsedUp} />}
    </section>
  );
}
