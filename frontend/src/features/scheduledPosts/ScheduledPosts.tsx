import { useState } from 'react';
import { useSubscribed } from '@/features/billing/useSubscribed';
import { useXConnectionContext } from '@/features/xConnection/useXConnectionContext';
import type { ScheduledPost } from '@/services/scheduledPostService';
import { CancelScheduledPostDialog } from './CancelScheduledPostDialog';
import { Composer } from './Composer';
import { EditScheduledPostDialog } from './EditScheduledPostDialog';
import { ScheduledPostLists } from './ScheduledPostLists';
import { useScheduledPosts } from './useScheduledPosts';

/** The composer and the lists it adds to. Needs an XConnectionProvider above it. */
export function ScheduledPosts() {
  const { scheduledPosts, loadFailed, posting, error, notice, postNow, schedule, edit, cancel } =
    useScheduledPosts();
  const { subscribed } = useSubscribed();
  const { connection } = useXConnectionContext();
  const [editing, setEditing] = useState<ScheduledPost | null>(null);
  const [cancelling, setCancelling] = useState<ScheduledPost | null>(null);
  // Editing goes by the X connection's limit, and rescheduling needs a connection that works.
  const usable = connection && !connection.needsReconnect ? connection : null;

  return (
    <>
      <Composer
        posting={posting}
        error={error}
        notice={notice}
        onPostNow={postNow}
        onSchedule={schedule}
      />
      <ScheduledPostLists
        scheduledPosts={scheduledPosts}
        loadFailed={loadFailed}
        onEdit={subscribed === true && usable ? setEditing : undefined}
        onCancel={subscribed === true ? setCancelling : undefined}
      />
      {usable && (
        <EditScheduledPostDialog
          post={editing}
          charLimit={usable.charLimit}
          onClose={() => setEditing(null)}
          onSave={(changes) => edit(editing!.id, changes)}
        />
      )}
      <CancelScheduledPostDialog
        post={cancelling}
        onClose={() => setCancelling(null)}
        onConfirm={() => cancel(cancelling!.id)}
      />
    </>
  );
}
