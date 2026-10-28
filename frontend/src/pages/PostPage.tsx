import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Link, useLocation, useParams } from 'react-router-dom';
import { ErrorBanner } from '@/components/ErrorBanner';
import { Button } from '@/components/ui/button';
import { PersonaChip } from '@/features/inspirationAuthors/PersonaChip';
import { BriefBlock } from '@/features/posts/BriefBlock';
import { opensEditing } from '@/features/posts/edit/scheduledPostEdit';
import { ScheduledPostEditor } from '@/features/posts/edit/ScheduledPostEditor';
import { DraftPanel } from '@/features/posts/panels/DraftPanel';
import { FailedPanel } from '@/features/posts/panels/FailedPanel';
import type { FeedbackSending } from '@/features/posts/panels/feedback';
import { PublishedPanel } from '@/features/posts/panels/PublishedPanel';
import { ScheduledPanel } from '@/features/posts/panels/ScheduledPanel';
import { PostBreadcrumb } from '@/features/posts/PostBreadcrumb';
import { hasScheduledPost, postTitle } from '@/features/posts/postStatus';
import { copiedText, retryParts, shownParts } from '@/features/posts/shownText';
import { usePost } from '@/features/posts/usePost';
import { VersionCard } from '@/features/posts/VersionCard';
import { VersionPager } from '@/features/posts/VersionPager';
import { Topbar } from '@/features/topbar/Topbar';
import { useXConnectionContext } from '@/features/xConnection/useXConnectionContext';
import type { PostDetail } from '@/services/postService';
import type { ScheduledPost } from '@/services/scheduledPostService';

/** The Version a Post opens on: the one its Scheduled post came from, else the latest. */
function openingIndex(post: PostDetail): number {
  const scheduled = post.versions.findIndex((v) => hasScheduledPost(post.scheduledPost, v.id));
  return scheduled >= 0 ? scheduled : post.versions.length - 1;
}

function Page({ title, children }: { title: ReactNode; children: ReactNode }) {
  return (
    <>
      <Topbar title={title} actions={<PersonaChip />} />
      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-2xl space-y-6 px-4 py-6 sm:px-6 sm:py-8">
          {children}
        </div>
      </div>
    </>
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
  const [index, setIndex] = useState(() => openingIndex(post));
  const [editing, setEditing] = useState(
    () => opensEditing(location.state) && post.scheduledPost?.state === 'scheduled',
  );
  const versionCount = useRef(post.versions.length);

  // A new Version from Feedback goes on screen as soon as it is in the Post.
  useEffect(() => {
    if (post.versions.length > versionCount.current) setIndex(post.versions.length - 1);
    versionCount.current = post.versions.length;
  }, [post.versions.length]);

  const shown = post.versions[Math.min(index, post.versions.length - 1)];
  const latest = post.versions[post.versions.length - 1];
  if (!shown || !latest) return null;
  const { scheduledPost } = post;
  const parts = shownParts(shown, scheduledPost, connection?.charLimit ?? null);
  const text = copiedText(parts);
  const title = postTitle(scheduledPost?.parts[0]?.text ?? latest.parts[0]?.text ?? post.brief);
  const breadcrumb = <PostBreadcrumb status={post.status} title={title} />;

  if (editing && scheduledPost?.state === 'scheduled') {
    const source = post.versions.findIndex((v) => v.id === scheduledPost.sourceVersionId);
    const stopEditing = () => {
      if (source >= 0) setIndex(source);
      setEditing(false);
    };
    return (
      <Page title={breadcrumb}>
        <BriefBlock brief={post.brief} />
        <ScheduledPostEditor
          version={post.versions[source] ?? shown}
          scheduledPost={scheduledPost}
          charLimit={connection?.charLimit ?? shown.parts[0]?.charLimit ?? 280}
          onSaved={(saved) => {
            onScheduledPost(saved);
            stopEditing();
          }}
          onUnscheduled={() => {
            onScheduledPost(null);
            stopEditing();
          }}
          onCancel={stopEditing}
        />
      </Page>
    );
  }

  return (
    <Page title={breadcrumb}>
      <BriefBlock brief={post.brief} />
      <div className="space-y-3">
        <VersionCard version={shown} parts={parts} />
        <VersionPager
          versions={post.versions}
          index={index}
          onChange={setIndex}
          scheduledPost={scheduledPost}
        />
      </div>
      {post.status === 'draft' && (
        <DraftPanel
          shownVersion={shown}
          shownParts={parts}
          shownText={text}
          latestVersion={latest}
          feedback={feedback}
          onScheduled={onScheduledPost}
        />
      )}
      {post.status === 'scheduled' && scheduledPost && (
        <ScheduledPanel
          post={post}
          scheduledPost={scheduledPost}
          shownText={text}
          onEdit={() => setEditing(true)}
        />
      )}
      {post.status === 'published' && scheduledPost && (
        <PublishedPanel post={post} scheduledPost={scheduledPost} shownText={text} />
      )}
      {post.status === 'failed' && scheduledPost && (
        <FailedPanel
          scheduledPost={scheduledPost}
          shownVersion={shown}
          retryParts={retryParts(shown, scheduledPost, connection?.charLimit ?? null)}
          shownText={text}
          latestVersion={latest}
          feedback={feedback}
          onRetried={onScheduledPost}
        />
      )}
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
          <Button asChild className="h-10">
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
    <Page title="Post">
      <p role="status" className="font-sans text-sm text-muted-foreground">
        Loading the Post…
      </p>
    </Page>
  );
}
