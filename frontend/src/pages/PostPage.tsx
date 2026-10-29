import { useEffect, useState, type ReactNode } from 'react';
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom';
import { ErrorBanner } from '@/components/ErrorBanner';
import { Button } from '@/components/ui/button';
import { PersonaChip } from '@/features/inspirationAuthors/PersonaChip';
import { CopyTextButton } from '@/features/posts/CopyTextButton';
import { opensEditing } from '@/features/posts/edit/scheduledPostEdit';
import { ScheduledPostEditor } from '@/features/posts/edit/ScheduledPostEditor';
import { DraftDock } from '@/features/posts/panels/DraftDock';
import { FailedDock } from '@/features/posts/panels/FailedDock';
import type { FeedbackSending } from '@/features/posts/panels/feedback';
import { LoadingDock } from '@/features/posts/panels/FeedbackDock';
import { OriginLine } from '@/features/posts/panels/OriginLine';
import { PublishedDock } from '@/features/posts/panels/PublishedDock';
import { ScheduledDock } from '@/features/posts/panels/ScheduledDock';
import { PostBreadcrumb } from '@/features/posts/PostBreadcrumb';
import { postTitle } from '@/features/posts/postStatus';
import { cardParts, copiedText, textVersionOf } from '@/features/posts/shownText';
import { TextCard } from '@/features/posts/TextCard';
import { usePost } from '@/features/posts/usePost';
import { Topbar } from '@/features/topbar/Topbar';
import { useXConnectionContext } from '@/features/xConnection/useXConnectionContext';
import type { PostDetail } from '@/services/postService';
import type { ScheduledPost } from '@/services/scheduledPostService';

/** The page's column scrolls under the Topbar; the dock, when there is one, stays pinned below. */
function Page({
  title,
  dock,
  children,
}: {
  title: ReactNode;
  dock?: ReactNode;
  children: ReactNode;
}) {
  return (
    <>
      <Topbar title={title} actions={<PersonaChip />} />
      <div className="flex-1 overflow-y-auto bg-background">
        <div className="mx-auto w-full max-w-[42rem] space-y-6 px-4 py-6 sm:px-6 sm:py-8">
          {children}
        </div>
      </div>
      {dock}
    </>
  );
}

function CardPlaceholder() {
  return (
    <div
      role="status"
      aria-label="Loading the Post"
      className="flex gap-3 rounded-xl border border-border bg-card px-4 py-4 sm:px-5"
    >
      <div aria-hidden className="h-10 w-10 shrink-0 rounded-full bg-muted" />
      <div aria-hidden className="flex-1 space-y-3 pt-1">
        <div className="h-3 w-40 rounded-full bg-muted" />
        <div className="h-3 w-full rounded-full bg-muted" />
        <div className="h-3 w-4/5 rounded-full bg-muted" />
        <div className="h-3 w-3/5 rounded-full bg-muted" />
      </div>
    </div>
  );
}

function LoadedPost({
  post,
  feedback,
  onScheduledPost,
}: {
  post: PostDetail;
  feedback: FeedbackSending;
  onScheduledPost: (scheduledPost: ScheduledPost | null) => void;
}) {
  const { connection } = useXConnectionContext();
  const location = useLocation();
  const [editing, setEditing] = useState(
    () => opensEditing(location.state) && post.scheduledPost?.state === 'scheduled',
  );
  const navigate = useNavigate();
  const opensEditor = opensEditing(location.state);

  // The request to edit is read once: a reload or a step back shows the Post, not the editor.
  useEffect(() => {
    if (opensEditor) navigate(location.pathname, { replace: true, state: null });
  }, [opensEditor, location.pathname, navigate]);

  const textVersion = textVersionOf(post);
  const latest = post.versions[post.versions.length - 1];
  if (!textVersion || !latest) return null;
  const { scheduledPost } = post;
  const charLimit = connection?.charLimit ?? null;
  const parts = cardParts(post, textVersion, charLimit);
  const title = postTitle(parts[0]?.text ?? post.brief);
  const breadcrumb = <PostBreadcrumb status={post.status} title={title} />;

  if (editing && scheduledPost?.state === 'scheduled') {
    return (
      <Page title={breadcrumb}>
        <ScheduledPostEditor
          scheduledPost={scheduledPost}
          charLimit={charLimit ?? textVersion.parts[0]?.charLimit ?? 280}
          onSaved={(saved) => {
            onScheduledPost(saved);
            setEditing(false);
          }}
          onUnscheduled={() => {
            onScheduledPost(null);
            setEditing(false);
          }}
          onCancel={() => setEditing(false)}
        />
      </Page>
    );
  }

  const origin = (
    <OriginLine
      brief={post.brief}
      version={textVersion}
      edited={post.text?.edited ?? false}
      writing={feedback.isWriting ? latest.number + 1 : null}
    />
  );

  let dock: ReactNode = null;
  if (post.status === 'draft') {
    dock = (
      <DraftDock
        textVersion={textVersion}
        parts={parts}
        origin={origin}
        feedback={feedback}
        onScheduled={onScheduledPost}
      />
    );
  } else if (post.status === 'failed' && scheduledPost) {
    dock = (
      <FailedDock
        scheduledPost={scheduledPost}
        textVersion={textVersion}
        retryParts={parts}
        origin={origin}
        feedback={feedback}
        onRetried={onScheduledPost}
      />
    );
  } else if (post.status === 'scheduled' && scheduledPost) {
    dock = (
      <ScheduledDock
        scheduledPost={scheduledPost}
        origin={origin}
        onEdit={() => setEditing(true)}
      />
    );
  } else if (post.status === 'published' && scheduledPost) {
    dock = <PublishedDock scheduledPost={scheduledPost} origin={origin} />;
  }

  return (
    <Page title={breadcrumb} dock={dock}>
      <TextCard
        parts={parts}
        busy={feedback.isWriting}
        corner={<CopyTextButton text={copiedText(parts)} disabled={feedback.isWriting} />}
      />
    </Page>
  );
}

/** One Post at /posts/:id, read from the server, so a reload shows the same Post. */
export function PostPage() {
  const { id = '' } = useParams();
  const { load, reload, setScheduledPost, addFeedback, isWriting, error, notice } = usePost(id);

  if (load.kind === 'loaded') {
    return (
      <LoadedPost
        key={load.post.id}
        post={load.post}
        feedback={{ isWriting, error, notice, onSend: addFeedback }}
        onScheduledPost={setScheduledPost}
      />
    );
  }
  if (load.kind === 'notFound') {
    return (
      <Page title="Post">
        <div className="space-y-3">
          <p className="font-sans text-sm text-foreground">
            This Post isn&apos;t here. It may have been written on another account.
          </p>
          <Button asChild variant="solid" className="h-10">
            <Link to="/new">Write a new Post</Link>
          </Button>
        </div>
      </Page>
    );
  }
  if (load.kind === 'failed') {
    return (
      <Page title="Post">
        <ErrorBanner message={load.message} onRetry={() => void reload()} />
      </Page>
    );
  }
  return (
    <Page title="Post" dock={<LoadingDock />}>
      <CardPlaceholder />
    </Page>
  );
}
