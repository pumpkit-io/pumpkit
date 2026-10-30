import { useEffect, useState, type ReactNode } from 'react';
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom';
import { ErrorBanner } from '@/components/ErrorBanner';
import { Button } from '@/components/ui/button';
import { PersonaChip } from '@/features/inspirationAuthors/PersonaChip';
import { CopyTextButton } from '@/features/posts/CopyTextButton';
import { HoverLabels } from '@/features/posts/HoverLabel';
import { opensEditing } from '@/features/posts/edit/scheduledPostEdit';
import { ScheduledPostEditor } from '@/features/posts/edit/ScheduledPostEditor';
import { DraftDock, DraftPostTo } from '@/features/posts/panels/DraftDock';
import { FailedDock, FailedPostTo } from '@/features/posts/panels/FailedDock';
import type { FeedbackSending } from '@/features/posts/panels/feedback';
import { LoadingDock } from '@/features/posts/panels/FeedbackDock';
import { recordDraftOpened } from '@/features/posts/list/recentDrafts';
import { HistoryButton } from '@/features/posts/panels/HistoryPanel';
import { OriginLine } from '@/features/posts/panels/OriginLine';
import { PublishedDock } from '@/features/posts/panels/PublishedDock';
import { ScheduledDock } from '@/features/posts/panels/ScheduledDock';
import { TextHeader } from '@/features/posts/panels/TextHeader';
import { UndoRedo } from '@/features/posts/panels/UndoRedo';
import { PostBreadcrumb } from '@/features/posts/PostBreadcrumb';
import { postTitle } from '@/features/posts/postStatus';
import { cardParts, copiedText } from '@/features/posts/shownText';
import type { TextController, TextSnapshot } from '@/features/posts/text/textController';
import { TextEditor } from '@/features/posts/TextEditor';
import { X_POST_MAX_CHARS } from '@/lib/xLength';
import { usePost } from '@/features/posts/usePost';
import { Topbar } from '@/features/topbar/Topbar';
import { useXConnectionContext } from '@/features/xConnection/useXConnectionContext';
import type { PostDetail } from '@/services/postService';
import type { ScheduledPost } from '@/services/scheduledPostService';

const COLUMN = 'mx-auto w-full max-w-[49rem] px-4 sm:px-6';

/**
 * The dock, when there is one, stays pinned under the Topbar. A `pinned` page holds the Post's
 * card in the height left, so only the card's Parts scroll; any other page scrolls as a whole.
 */
function Page({
  title,
  dock,
  pinned = false,
  children,
}: {
  title: ReactNode;
  dock?: ReactNode;
  pinned?: boolean;
  children: ReactNode;
}) {
  return (
    <>
      <Topbar title={title} actions={<PersonaChip />} />
      {dock}
      {pinned ? (
        <div className="flex min-h-0 flex-1 flex-col bg-background">
          <div className={`${COLUMN} flex min-h-0 flex-col pb-4 pt-6 sm:pb-6`}>{children}</div>
        </div>
      ) : (
        <div className="flex-1 overflow-y-auto bg-background">
          <div className={`${COLUMN} space-y-6 py-6 sm:py-8`}>{children}</div>
        </div>
      )}
    </>
  );
}

function CardPlaceholder() {
  return (
    <div
      role="status"
      aria-label="Loading the post"
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
  post: loaded,
  text,
  controller,
  feedback,
  rewritesDropped,
  onScheduledPost,
}: {
  post: PostDetail;
  text: TextSnapshot;
  controller: TextController;
  feedback: FeedbackSending;
  /** An edit just dropped rewrites from redo, which History still holds. */
  rewritesDropped: boolean;
  onScheduledPost: (scheduledPost: ScheduledPost | null) => void;
}) {
  const post: PostDetail = { ...loaded, text: text.text, versions: text.versions };
  const { connection } = useXConnectionContext();
  const location = useLocation();
  const opensEditor = opensEditing(location.state);
  const [editing, setEditing] = useState(
    () => opensEditor && post.scheduledPost?.state === 'scheduled',
  );
  const navigate = useNavigate();

  // The request to edit is read once: a reload or a step back shows the Post, not the editor.
  useEffect(() => {
    if (opensEditor) navigate(location.pathname, { replace: true, state: null });
  }, [opensEditor, location.pathname, navigate]);

  useEffect(() => {
    if (post.status === 'draft') recordDraftOpened(post.id);
  }, [post.id, post.status]);

  const { textVersion, can } = text;
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
          charLimit={charLimit ?? textVersion.parts[0]?.charLimit ?? X_POST_MAX_CHARS}
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
      writing={text.writing ? latest.number + 1 : null}
      save={text.save}
      rewritesDropped={rewritesDropped}
    />
  );

  const textChanges = post.status === 'draft' || post.status === 'failed';
  const onUndo = can.undo ? () => controller.undo() : undefined;
  const onRedo = can.redo ? () => controller.redo() : undefined;
  const settle = () => controller.settle();
  const tools = (
    <HoverLabels>
      <div className="flex shrink-0 items-center gap-0.5">
        {textChanges && <UndoRedo onUndo={onUndo} onRedo={onRedo} />}
        <HistoryButton
          brief={post.brief}
          versions={post.versions}
          textVersionNumber={textVersion.number}
          edited={post.text?.edited ?? false}
          onRestore={can.restore ? (n) => controller.restore(n) : undefined}
        />
        <CopyTextButton text={copiedText(parts)} disabled={text.writing} />
      </div>
    </HoverLabels>
  );

  let dock: ReactNode = null;
  let postTo: ReactNode = null;
  if (post.status === 'draft') {
    dock = (
      <DraftDock textVersion={textVersion} feedback={feedback} restoreError={text.restoreError} />
    );
    postTo = (
      <DraftPostTo
        postId={post.id}
        textVersion={textVersion}
        parts={parts}
        disabled={!can.postTo}
        prepare={settle}
        onScheduled={onScheduledPost}
      />
    );
  } else if (post.status === 'failed' && scheduledPost) {
    dock = (
      <FailedDock
        scheduledPost={scheduledPost}
        textVersion={textVersion}
        feedback={feedback}
        restoreError={text.restoreError}
      />
    );
    postTo = (
      <FailedPostTo
        scheduledPost={scheduledPost}
        textVersion={textVersion}
        retryParts={parts}
        disabled={!can.postTo}
        prepare={settle}
        onRetried={onScheduledPost}
      />
    );
  } else if (post.status === 'scheduled' && scheduledPost) {
    dock = <ScheduledDock scheduledPost={scheduledPost} onEdit={() => setEditing(true)} />;
  } else if (post.status === 'published' && scheduledPost) {
    dock = <PublishedDock scheduledPost={scheduledPost} />;
  }

  return (
    <Page title={breadcrumb} dock={dock} pinned>
      <TextEditor
        parts={parts}
        texts={post.text?.parts.map((p) => p.text) ?? []}
        editable={can.edit}
        onEdit={(texts, change) => controller.edit(texts, change.cause)}
        onUndo={onUndo}
        onRedo={onRedo}
        trace={text.trace}
        busy={text.writing}
        header={<TextHeader origin={origin} tools={tools} action={postTo} />}
      />
      <p role="status" className="sr-only">
        {text.announcement && <span key={text.announcement.key}>{text.announcement.message}</span>}
      </p>
    </Page>
  );
}

/** One Post at /posts/:id, read from the server, so a reload shows the same Post. */
export function PostPage() {
  const { id = '' } = useParams();
  const { load, reload, setScheduledPost, text, sendFeedback, rewritesDropped, error, notice } =
    usePost(id);

  if (load.kind === 'loaded' && text) {
    return (
      <LoadedPost
        key={load.post.id}
        post={load.post}
        text={text}
        controller={load.controller}
        feedback={{ isWriting: text.writing, error, notice, onSend: sendFeedback }}
        rewritesDropped={rewritesDropped}
        onScheduledPost={setScheduledPost}
      />
    );
  }
  if (load.kind === 'notFound') {
    return (
      <Page title="Post">
        <div className="space-y-3">
          <p className="font-sans text-sm text-foreground">
            This post isn&apos;t here. It may have been written on another account.
          </p>
          <Button asChild variant="solid" className="h-10">
            <Link to="/new">Write a new post</Link>
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
    <Page title="Post" dock={<LoadingDock />} pinned>
      <CardPlaceholder />
    </Page>
  );
}
