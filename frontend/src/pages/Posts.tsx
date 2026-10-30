import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { ErrorBanner } from '@/components/ErrorBanner';
import { Button } from '@/components/ui/button';
import { PostRow } from '@/features/posts/list/PostRow';
import { PostsTabs } from '@/features/posts/list/PostsTabs';
import { TAB_ORDER_LINE } from '@/features/posts/postStatus';
import { usePostsTab } from '@/features/posts/list/usePostsTab';
import { usePostCounts } from '@/features/posts/usePostCounts';
import { TIME_ZONE } from '@/features/scheduledPosts/localTime';
import { Topbar } from '@/features/topbar/Topbar';
import { useXConnectionContext } from '@/features/xConnection/useXConnectionContext';
import type { PostStatus } from '@/services/postService';

const LINK = 'font-medium text-foreground underline underline-offset-2';

/** Which X account and clock the times on the page belong to. */
function PostingAs() {
  const { connection } = useXConnectionContext();
  return (
    <p className="min-w-0 truncate font-sans text-xs text-muted-foreground">
      {connection ? (
        <>
          Posting as <span className="font-medium text-foreground">@{connection.handle}</span>
        </>
      ) : (
        <Link to="/settings" className={LINK}>
          Connect X to post
        </Link>
      )}
      <span aria-hidden> · </span>
      <span className="sr-only">, times in </span>
      {TIME_ZONE}
    </p>
  );
}

/** What an empty tab says, and where to go instead. */
const EMPTY: Record<PostStatus, ReactNode> = {
  scheduled: (
    <>
      Nothing scheduled. Open one of your{' '}
      <Link to="/posts/drafts" className={LINK}>
        Drafts
      </Link>{' '}
      to post it to X.
    </>
  ),
  draft: (
    <>
      No drafts. Write one on{' '}
      <Link to="/new" className={LINK}>
        New post
      </Link>
      .
    </>
  ),
  published: 'Nothing published yet. Posts you publish show up here with a link to X.',
  failed: 'Nothing failed. A Post X refuses shows up here with the reason.',
};

function TabBody({ status }: { status: PostStatus }) {
  const { load, retry, showMore } = usePostsTab(status);
  const { connection } = useXConnectionContext();

  if (load.kind === 'loading') {
    return (
      <p role="status" className="font-sans text-sm text-muted-foreground">
        Loading your posts…
      </p>
    );
  }
  if (load.kind === 'failed') return <ErrorBanner message={load.message} onRetry={retry} />;
  if (load.posts.length === 0) {
    return <p className="font-sans text-sm text-muted-foreground">{EMPTY[status]}</p>;
  }
  return (
    <div className="space-y-4">
      <ul className="divide-y divide-border rounded-xl border border-border bg-card text-card-foreground">
        {load.posts.map((post) => (
          <PostRow key={post.id} post={post} charLimit={connection?.charLimit ?? null} />
        ))}
      </ul>
      {load.more === 'failed' && (
        <ErrorBanner message="Couldn't load more posts." onRetry={showMore} />
      )}
      {load.nextOffset !== null && load.more !== 'failed' && (
        <Button
          type="button"
          variant="outline"
          className="w-full"
          disabled={load.more === 'loading'}
          onClick={showMore}
        >
          {load.more === 'loading' ? 'Loading…' : 'Show more'}
        </Button>
      )}
    </div>
  );
}

/** Every Post by status, one tab per status at its own address. Rendered inside AppLayout. */
export function Posts({ status }: { status: PostStatus }) {
  const { counts } = usePostCounts();
  return (
    <>
      <Topbar title="Posts" actions={<PostingAs />} />
      {/* Reserve the scrollbar's space so switching between short and long tabs doesn't shift the page. */}
      <div className="flex-1 overflow-y-auto [scrollbar-gutter:stable_both-edges]">
        <div className="mx-auto w-full max-w-2xl space-y-4 px-4 py-6 sm:px-6 sm:py-8">
          <PostsTabs counts={counts} />
          <p className="font-sans text-xs text-muted-foreground">{TAB_ORDER_LINE[status]}</p>
          <TabBody key={status} status={status} />
        </div>
      </div>
    </>
  );
}
