import { useEffect, useState, type ReactNode } from 'react';
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom';
import { ErrorBanner } from '@/components/ErrorBanner';
import { Button } from '@/components/ui/button';
import { useSubscribed } from '@/features/billing/useSubscribed';
import { PersonaChip } from '@/features/inspirationAuthors/PersonaChip';
import { CopyTextButton } from '@/features/posts/CopyTextButton';
import { HoverLabels } from '@/features/posts/HoverLabel';
import { opensEditing } from '@/features/posts/edit/scheduledPostEdit';
import { ScheduledPostEditor } from '@/features/posts/edit/ScheduledPostEditor';
import { DraftDock, DraftPostTo } from '@/features/posts/panels/DraftDock';
import { FailedDock, FailedPostTo } from '@/features/posts/panels/FailedDock';
import type { FeedbackSending } from '@/features/posts/panels/feedback';
import { LoadingDock } from '@/features/posts/panels/FeedbackDock';
import { HistoryButton } from '@/features/posts/panels/HistoryPanel';
import { OriginLine } from '@/features/posts/panels/OriginLine';
import { PublishedDock } from '@/features/posts/panels/PublishedDock';
import { ScheduledDock } from '@/features/posts/panels/ScheduledDock';
import { TextHeader } from '@/features/posts/panels/TextHeader';
import { UndoRedo } from '@/features/posts/panels/UndoRedo';
import { PostBreadcrumb } from '@/features/posts/PostBreadcrumb';
import { postTitle } from '@/features/posts/postStatus';
import { cardParts, copiedText, versionOnScreen } from '@/features/posts/shownText';
import { TextEditor, type TextChange } from '@/features/posts/TextEditor';
import { X_POST_MAX_CHARS } from '@/lib/xLength';
import type { TextSaveState } from '@/features/posts/useTextAutosave';
import type { TextTrace, UndoAnnouncement } from '@/features/posts/useUndoLine';
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

/** The in-place editing of the Text, with undo and redo, from `usePost`. */
interface TextEditing {
  onEdit: (texts: string[], change: TextChange) => void;
  save: TextSaveState;
  /** Saves the last edit now; true once the server has it. */
  flush: () => Promise<boolean>;
  /** Left out at either end of the undo line. */
  onUndo?: () => void;
  onRedo?: () => void;
  trace: TextTrace | null;
  announcement: UndoAnnouncement | null;
  rewritesDropped: boolean;
}

function LoadedPost({
  post,
  feedback,
  restore,
  edit,
  onScheduledPost,
}: {
  post: PostDetail;
  feedback: FeedbackSending;
  restore: {
    onRestore: (versionNumber: number) => void;
    isRestoring: boolean;
    error: string | null;
  };
  edit: TextEditing;
  onScheduledPost: (scheduledPost: ScheduledPost | null) => void;
}) {
  const { connection } = useXConnectionContext();
  const { subscribed } = useSubscribed();
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

  const textVersion = versionOnScreen(post);
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
      writing={feedback.isWriting ? latest.number + 1 : null}
      save={edit.save}
      rewritesDropped={edit.rewritesDropped}
    />
  );

  const textChanges = post.status === 'draft' || post.status === 'failed';
  const editable = textChanges && !!post.text && subscribed === true && !feedback.isWriting;
  const onUndo = editable ? edit.onUndo : undefined;
  const onRedo = editable ? edit.onRedo : undefined;
  const tools = (
    <HoverLabels>
      <div className="flex shrink-0 items-center gap-0.5">
        {textChanges && <UndoRedo onUndo={onUndo} onRedo={onRedo} />}
        <HistoryButton
          brief={post.brief}
          versions={post.versions}
          textVersionNumber={textVersion.number}
          edited={post.text?.edited ?? false}
          onRestore={
            textChanges && !feedback.isWriting && !restore.isRestoring
              ? restore.onRestore
              : undefined
          }
        />
        <CopyTextButton text={copiedText(parts)} disabled={feedback.isWriting} />
      </div>
    </HoverLabels>
  );

  let dock: ReactNode = null;
  let postTo: ReactNode = null;
  if (post.status === 'draft') {
    dock = <DraftDock textVersion={textVersion} feedback={feedback} restoreError={restore.error} />;
    postTo = (
      <DraftPostTo
        postId={post.id}
        textVersion={textVersion}
        parts={parts}
        disabled={feedback.isWriting}
        prepare={edit.flush}
        onScheduled={onScheduledPost}
      />
    );
  } else if (post.status === 'failed' && scheduledPost) {
    dock = (
      <FailedDock
        scheduledPost={scheduledPost}
        textVersion={textVersion}
        feedback={feedback}
        restoreError={restore.error}
      />
    );
    postTo = (
      <FailedPostTo
        scheduledPost={scheduledPost}
        textVersion={textVersion}
        retryParts={parts}
        disabled={feedback.isWriting}
        prepare={edit.flush}
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
        editable={editable}
        onEdit={edit.onEdit}
        onUndo={onUndo}
        onRedo={onRedo}
        trace={edit.trace}
        busy={feedback.isWriting}
        header={<TextHeader origin={origin} tools={tools} action={postTo} />}
      />
      <p role="status" className="sr-only">
        {edit.announcement && <span key={edit.announcement.key}>{edit.announcement.message}</span>}
      </p>
    </Page>
  );
}

/** One Post at /posts/:id, read from the server, so a reload shows the same Post. */
export function PostPage() {
  const { id = '' } = useParams();
  const {
    load,
    reload,
    setScheduledPost,
    addFeedback,
    restoreVersion,
    restoreError,
    isRestoring,
    editText,
    undo,
    redo,
    trace,
    announcement,
    rewritesDropped,
    textSave,
    flushText,
    isWriting,
    error,
    notice,
  } = usePost(id);

  if (load.kind === 'loaded') {
    return (
      <LoadedPost
        key={load.post.id}
        post={load.post}
        feedback={{ isWriting, error, notice, onSend: addFeedback }}
        restore={{ onRestore: restoreVersion, isRestoring, error: restoreError }}
        edit={{
          onEdit: (texts, change) => editText(texts, change.cause),
          save: textSave,
          flush: flushText,
          onUndo: undo,
          onRedo: redo,
          trace,
          announcement,
          rewritesDropped,
        }}
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
    <Page title="Post" dock={<LoadingDock />} pinned>
      <CardPlaceholder />
    </Page>
  );
}
