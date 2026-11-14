import type { ReactNode } from 'react';
import { Link, useParams } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import { ErrorBanner } from '@/components/ErrorBanner';
import { Button } from '@/components/ui/button';
import { useBrief } from '@/features/briefs/useBrief';
import { PersonaLink } from '@/features/positioning/PersonaLink';
import { Topbar } from '@/features/topbar/Topbar';
import { briefPosts, type BriefPost, type Idea } from '@/services/briefService';

const COLUMN = 'mx-auto w-full max-w-[49rem] px-4 sm:px-6';
const CARD = 'rounded-xl border border-border bg-card px-4 py-4 sm:px-5';
// The lines a written post would fill, widest first, as the Post page's writing card draws them.
const LINES = ['w-full', 'w-4/5', 'w-3/5'];

function Page({ children }: { children: ReactNode }) {
  return (
    <>
      <Topbar title="Posts from your brief" actions={<PersonaLink />} />
      <div className="flex-1 overflow-y-auto bg-background">
        <div className={`${COLUMN} space-y-6 py-6 sm:py-8`}>
          <Link
            to="/new"
            className="inline-flex items-center gap-1.5 font-sans text-[13px] text-muted-foreground hover:text-foreground"
          >
            <ArrowLeft className="h-3.5 w-3.5" aria-hidden />
            New post
          </Link>
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

function CardText({ post }: { post: BriefPost }) {
  if (post.writingState === 'writing') return <Writing />;
  if (!post.text)
    return (
      <p className="font-sans text-[15px] text-foreground">
        This post couldn&apos;t be written. Open it to retry.
      </p>
    );
  const [first] = post.text.parts;
  return (
    <p className="whitespace-pre-wrap break-words font-sans text-[15px] leading-6 text-foreground">
      {first?.text}
    </p>
  );
}

function PostCard({ idea, post }: { idea: Idea; post: BriefPost }) {
  const coreIdea = idea.plan?.coreIdea ?? 'Your post';
  return (
    <li aria-label={coreIdea} className="space-y-2">
      <p className="flex gap-3 font-sans text-[13px] text-muted-foreground">
        <span aria-hidden className="tabular-nums">
          {idea.postingOrder}
        </span>
        <span>{coreIdea}</span>
      </p>
      <div className={CARD}>
        <CardText post={post} />
      </div>
      <Link
        to={`/posts/${post.id}`}
        aria-label={`Open “${coreIdea}”`}
        className="inline-block font-sans text-[13px] font-medium text-foreground underline-offset-2 hover:underline"
      >
        Open
      </Link>
    </li>
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
 * The Posts written from one Brief, in posting order, each with its core idea and its text, or
 * its writing state until it is written (ADR 0025). It reads the Brief again while any is written.
 */
export function BriefPage() {
  const { id = '' } = useParams<{ id: string }>();
  const { load, reload } = useBrief(id);

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
          This brief isn&apos;t here. It may have been written on another account.
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
  return (
    <Page>
      <p className="line-clamp-2 max-w-[68ch] font-sans text-[15px] text-muted-foreground">
        “{brief.text}”
      </p>
      {posts.length === 0 ? (
        <p className="font-sans text-sm text-foreground">
          No post from this brief is written yet.{' '}
          <Link to="/new" className="underline underline-offset-2">
            Write a new post
          </Link>
        </p>
      ) : (
        <ol className="max-w-[68ch] space-y-8">
          {posts.map(({ idea, post }) => (
            <PostCard key={idea.id} idea={idea} post={post} />
          ))}
        </ol>
      )}
    </Page>
  );
}
