import { useState, type ReactNode } from 'react';
import { Link, Navigate, useParams } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import { ErrorBanner } from '@/components/ErrorBanner';
import { Notice } from '@/components/Notice';
import { Button } from '@/components/ui/button';
import { AllowanceNotice } from '@/features/billing/AllowanceNotice';
import { useBrief, type BriefFailure } from '@/features/briefs/useBrief';
import { CharacterCount } from '@/features/posts/CharacterCount';
import { planLine } from '@/features/posts/planLine';
import { partSubject, shapeName } from '@/features/posts/postShape';
import { postTitle } from '@/features/posts/postStatus';
import { PostToButton } from '@/features/posts/postTo/PostToButton';
import { useCreateFromText } from '@/features/posts/postTo/senders';
import type { ShownPart } from '@/features/posts/shownText';
import { PersonaLink } from '@/features/positioning/PersonaLink';
import { StatusBadge } from '@/features/scheduledPosts/StatusBadge';
import { Topbar } from '@/features/topbar/Topbar';
import { briefPosts, notWrittenIdeas, type BriefPost, type Idea } from '@/services/briefService';
import { FORMAT_THREAD, type PostText } from '@/services/postService';

const COLUMN = 'mx-auto w-full max-w-[49rem] px-4 sm:px-6';
const CARD = 'rounded-xl border border-border bg-card px-4 py-4 sm:px-5';
const POST_TEXT = 'whitespace-pre-wrap break-words font-sans text-[15px] leading-6 text-foreground';
// The lines a written post would fill, widest first, as the Post page's writing card draws them.
const LINES = ['w-full', 'w-4/5', 'w-3/5'];

function Page({ written, children }: { written?: ReactNode; children: ReactNode }) {
  return (
    <>
      <Topbar title="Posts from your brief" actions={<PersonaLink />} />
      <div className="flex-1 overflow-y-auto bg-background">
        <div className={`${COLUMN} space-y-6 py-6 sm:py-8`}>
          <div className="flex items-center justify-between gap-4">
            <Link
              to="/new"
              className="inline-flex items-center gap-1.5 font-sans text-[13px] text-muted-foreground hover:text-foreground"
            >
              <ArrowLeft className="h-3.5 w-3.5" aria-hidden />
              New post
            </Link>
            {written}
          </div>
          {children}
        </div>
      </div>
    </>
  );
}

/** The card's own state while its Post is written: lines filling in, or still with reduced motion. */
function Writing() {
  return (
    <div role="status" className="space-y-3">
      <p className="font-sans text-[15px] text-foreground">Writing…</p>
      <div aria-hidden className="space-y-3">
        {LINES.map((width, index) => (
          <div key={width} className={`h-3 overflow-hidden rounded-full bg-muted ${width}`}>
            <div
              className="post-writing-line h-full rounded-full bg-primary/20"
              style={{ animationDelay: `${index * 0.4}s` }}
            />
          </div>
        ))}
      </div>
    </div>
  );
}

/** Why asking to write an Idea or retry its Post failed, where the User asked. */
function Failure({ failure }: { failure: BriefFailure }) {
  if (failure.allowanceUsedUp) return <AllowanceNotice refusal={failure.allowanceUsedUp} />;
  if (failure.notice) return <Notice message={failure.notice} />;
  if (failure.error) return <ErrorBanner message={failure.error} />;
  return null;
}

/** Part 1, and a single post's first reply under it. */
function WrittenText({ text }: { text: PostText }) {
  const [first] = text.parts;
  const reply = text.firstReply ? text.parts.at(-1) : undefined;
  return (
    <>
      <p className={POST_TEXT}>{first?.text}</p>
      {reply && (
        <div role="group" aria-label="First reply" className="mt-4 border-t border-border pt-3">
          <p className="mb-1 font-sans text-[13px] text-muted-foreground">First reply</p>
          <p className={POST_TEXT}>{reply.text}</p>
        </div>
      )}
    </>
  );
}

/** Part 1's count, a Thread's Part count, any other Part over the limit, and the Plan. */
function Facts({ idea, text }: { idea: Idea; text: PostText }) {
  const [first] = text.parts;
  const count = text.parts.length;
  const over = text.parts.flatMap((part, i) =>
    i > 0 && part.charCount > part.charLimit
      ? [`${partSubject(i, count, text.firstReply)} is over the limit.`]
      : [],
  );
  return (
    <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 font-sans text-[13px] text-muted-foreground">
      {first && (
        <CharacterCount count={first.charCount} limit={first.charLimit} className="font-mono" />
      )}
      {text.format === FORMAT_THREAD && <p>{shapeName(count, text.firstReply)}</p>}
      {over.map((line) => (
        <p key={line} className="text-destructive">
          {line}
        </p>
      ))}
      {idea.plan && <p>{planLine(idea.plan, text.format)}</p>}
    </div>
  );
}

/** "Post to…" for a Draft's card, which sends its Text with its Media; off while it is rewritten. */
function CardPostTo({
  post,
  text,
  onDone,
}: {
  post: BriefPost;
  text: PostText;
  onDone: () => void;
}) {
  const sender = useCreateFromText(post.id);
  const parts: ShownPart[] = text.parts.map((part, i) => ({
    ...part,
    live: false,
    xPostUrl: null,
    media: post.textMedia[i] ?? [],
    firstReply: text.firstReply && i === text.parts.length - 1,
  }));
  return (
    <PostToButton
      quiet
      format={text.format}
      parts={parts}
      sender={sender}
      disabled={post.writingState === 'writing'}
      onDone={onDone}
    />
  );
}

function PostCard({
  idea,
  post,
  place,
  busy,
  failure,
  onRetry,
  onSent,
}: {
  idea: Idea;
  post: BriefPost;
  /** Its place among the Brief's Posts, from 1. */
  place: number;
  busy: boolean;
  failure: BriefFailure | undefined;
  onRetry: () => void;
  /** After "Post to…" scheduled it or posted it now. */
  onSent: () => void;
}) {
  const coreIdea = idea.plan?.coreIdea ?? 'Your post';
  const { text, status } = post;
  let body: ReactNode;
  if (post.writingState === 'writing') body = <Writing />;
  else if (!text)
    body = (
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <p className="font-sans text-[15px] text-foreground">This post couldn&apos;t be written.</p>
        <Button type="button" variant="outline" className="h-10" disabled={busy} onClick={onRetry}>
          {busy ? 'Retrying…' : 'Retry'}
        </Button>
      </div>
    );
  else body = <WrittenText text={text} />;

  return (
    <li aria-label={coreIdea} className="space-y-2">
      <p className="flex gap-3 font-sans text-[13px] text-muted-foreground">
        <span aria-hidden className="tabular-nums">
          {place}
        </span>
        <span>{coreIdea}</span>
      </p>
      <div className={CARD}>{body}</div>
      {text && <Facts idea={idea} text={text} />}
      <div className="flex flex-wrap items-center gap-2 pt-1">
        <Button asChild variant="outline" className="h-10">
          <Link to={`/posts/${post.id}`} aria-label={`Open “${coreIdea}”`}>
            Open
          </Link>
        </Button>
        {text && status === 'draft' && <CardPostTo post={post} text={text} onDone={onSent} />}
        {text && status && status !== 'draft' && (
          <StatusBadge status={status} publishing={post.publishing} />
        )}
      </div>
      {failure && <Failure failure={failure} />}
    </li>
  );
}

function NotWritten({
  ideas,
  busy,
  failures,
  onWrite,
}: {
  ideas: Idea[];
  busy: ReadonlySet<string>;
  failures: Readonly<Record<string, BriefFailure>>;
  onWrite: (ideaId: string) => void;
}) {
  return (
    <section aria-labelledby="not-written" className="max-w-[68ch] space-y-3">
      <h2 id="not-written" className="font-sans text-[13px] font-medium text-foreground">
        Not written
      </h2>
      <ul aria-labelledby="not-written" className="divide-y divide-border border-y border-border">
        {ideas.map((idea) => {
          const coreIdea = idea.plan?.coreIdea ?? 'Your post';
          const failure = failures[idea.id];
          return (
            <li key={idea.id} aria-label={coreIdea} className="space-y-2 py-3">
              <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
                <div className="min-w-0 font-sans text-sm text-foreground">
                  <p>{coreIdea}</p>
                  {idea.wholeBrief && (
                    <p className="text-[13px] text-muted-foreground">
                      One post covering everything
                    </p>
                  )}
                </div>
                <Button
                  type="button"
                  variant="outline"
                  className="h-10 shrink-0"
                  aria-label={`Write “${coreIdea}”`}
                  disabled={busy.has(idea.id)}
                  onClick={() => onWrite(idea.id)}
                >
                  {busy.has(idea.id) ? 'Starting…' : 'Write this one'}
                </Button>
              </div>
              {failure && <Failure failure={failure} />}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

/** The Brief's first line as a quote, and on "Show brief" its whole text. */
function BriefLine({ text }: { text: string }) {
  const [shown, setShown] = useState(false);
  const preview = postTitle(text);
  const cut = preview !== text.trim();
  return (
    <div className="max-w-[68ch] space-y-2 font-sans text-[15px] text-muted-foreground">
      <p className="flex flex-wrap items-baseline gap-x-3">
        {!shown && <span>“{preview}”</span>}
        {cut && (
          <button
            type="button"
            aria-expanded={shown}
            onClick={() => setShown((open) => !open)}
            className="rounded-sm text-[13px] font-medium text-foreground underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {shown ? 'Hide brief' : 'Show brief'}
          </button>
        )}
      </p>
      {shown && <p className="whitespace-pre-wrap break-words">{text}</p>}
    </div>
  );
}

function Placeholders() {
  return (
    <div role="status" aria-label="Loading the brief" className="space-y-6">
      <div aria-hidden className="h-3 w-64 rounded-full bg-muted" />
      {[1, 2, 3].map((n) => (
        <div key={n} aria-hidden className="space-y-2">
          <p className="font-sans text-[13px] tabular-nums text-muted-foreground">{n}</p>
          <div className={`${CARD} space-y-3`}>
            <div className="h-3 w-full rounded-full bg-muted" />
            <div className="h-3 w-4/5 rounded-full bg-muted" />
          </div>
        </div>
      ))}
    </div>
  );
}

/**
 * The Posts written from one Brief, in the Brief's order, each with its core idea and its text, or
 * its writing state until it is written, and the Ideas still to write (ADR 0025). It reads the
 * Brief again while any is written. A Brief with one Post and no Idea left goes to that Post.
 */
export function BriefPage() {
  const { id = '' } = useParams<{ id: string }>();
  const { load, reload, refresh, write, retry, busy, failures } = useBrief(id);

  if (load.kind === 'loading')
    return (
      <Page>
        <Placeholders />
      </Page>
    );
  if (load.kind === 'notFound')
    return (
      <Page>
        <p className="font-sans text-sm text-foreground">
          This brief doesn&apos;t exist, or it isn&apos;t yours.
        </p>
        <Button asChild variant="solid" className="h-10">
          <Link to="/new">Write a new post</Link>
        </Button>
      </Page>
    );
  if (load.kind === 'failed')
    return (
      <Page>
        <ErrorBanner message={load.message} onRetry={() => void reload()} />
      </Page>
    );

  const { brief } = load;
  const posts = briefPosts(brief);
  const offered = notWrittenIdeas(brief);
  const [only] = posts;
  if (only && posts.length === 1 && offered.length === 0)
    return <Navigate to={`/posts/${only.post.id}`} replace />;
  // The Brief's Posts, written or not, out of those and the Ideas still offered.
  const count =
    posts.length > 0 ? `${posts.length} of ${posts.length + offered.length} written` : null;
  return (
    <Page
      written={
        count && <p className="font-sans text-[13px] tabular-nums text-muted-foreground">{count}</p>
      }
    >
      <BriefLine text={brief.text} />
      {posts.length > 0 && (
        <ol aria-label="Posts" className="max-w-[68ch] space-y-8">
          {posts.map(({ idea, post }, index) => (
            <PostCard
              key={idea.id}
              idea={idea}
              post={post}
              place={index + 1}
              busy={busy.has(idea.id)}
              failure={failures[idea.id]}
              onRetry={() => void retry(idea.id, post.id)}
              onSent={() => void refresh()}
            />
          ))}
        </ol>
      )}
      {offered.length > 0 && (
        <NotWritten
          ideas={offered}
          busy={busy}
          failures={failures}
          onWrite={(ideaId) => void write(ideaId)}
        />
      )}
    </Page>
  );
}
