import { useEffect, useRef, useState } from 'react';
import { useXConnectionContext } from '@/features/xConnection/useXConnectionContext';
import { errorStatus } from '@/services/apiErrors';
import { postService } from '@/services/postService';
import type { ScheduledPost } from '@/services/scheduledPostService';

/** The waits between reads of a posting Post, the last one repeating for as long as it posts. */
export const POSTING_READS_MS = [3_000, 5_000, 10_000, 20_000, 30_000];
// A day covers any open page; setTimeout itself would fire at once past about 24.8 days.
const LONGEST_WAIT_MS = 24 * 60 * 60 * 1000;

/** Whether a read shows what the page shows, posting as the page has it, flipped or not. */
function showsTheSame(read: ScheduledPost | null, shown: ScheduledPost | null, posting: boolean) {
  return (
    read?.id === shown?.id &&
    read?.state === shown?.state &&
    read?.publishAt === shown?.publishAt &&
    (read?.posting ?? false) === posting
  );
}

type Waiting = Pick<ScheduledPost, 'state' | 'publishAt' | 'posting'>;

/**
 * Whether the Scheduled post is posting, as the server answered it, or since its time came while
 * the page sat open: the server's `posting` holds again once the Scheduled post is read anew.
 */
export function useIsPosting(scheduledPost: Waiting | null): boolean {
  const [cameDue, setCameDue] = useState<Waiting | null>(null);
  const state = scheduledPost?.state;
  const publishAt = scheduledPost?.publishAt;

  useEffect(() => {
    if (state !== 'scheduled' || publishAt === undefined) return;
    const wait = Date.parse(publishAt) - Date.now();
    if (wait <= 0 || wait > LONGEST_WAIT_MS) return;
    const timer = setTimeout(() => setCameDue(scheduledPost), wait);
    return () => clearTimeout(timer);
    // The timer belongs to the moment, not to each copy of the same Scheduled post.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state, publishAt]);

  if (!scheduledPost) return false;
  return scheduledPost.posting || (cameDue === scheduledPost && state === 'scheduled');
}

/**
 * Whether the Scheduled post is posting, as `useIsPosting` says. While it is, or while it waits
 * for a retry after X was busy, reads the Post again, less and less often and only while the tab
 * is visible, and passes on each change of its Scheduled post to `onChange` until it is Published
 * or Failed. A Failed one reloads the X connection, which it may have flagged for reconnecting.
 */
export function usePosting(
  postId: string,
  scheduledPost: ScheduledPost | null,
  onChange: (scheduledPost: ScheduledPost | null) => void,
  onGone: () => void,
): boolean {
  const posting = useIsPosting(scheduledPost);
  const { reload: reloadXConnection } = useXConnectionContext();
  const retrying =
    scheduledPost?.state === 'scheduled' &&
    !posting &&
    Date.parse(scheduledPost.publishAt) <= Date.now();
  const reading = posting || retrying;

  const latest = useRef({ scheduledPost, posting, onChange, onGone, reloadXConnection });
  latest.current = { scheduledPost, posting, onChange, onGone, reloadXConnection };

  useEffect(() => {
    if (!reading) return;
    let reads = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let stopped = false;

    const read = async () => {
      if (document.visibilityState === 'hidden') {
        document.addEventListener('visibilitychange', read, { once: true });
        return;
      }
      try {
        const { scheduledPost: current } = await postService.get(postId);
        if (stopped) return;
        const shown = latest.current;
        if (!showsTheSame(current, shown.scheduledPost, shown.posting)) {
          if (current?.state === 'failed') void shown.reloadXConnection();
          shown.onChange(current);
        }
      } catch (e) {
        if (stopped) return;
        if (errorStatus(e) === 404) {
          latest.current.onGone();
          return;
        }
      }
      if (stopped) return;
      reads += 1;
      waitThenRead();
    };

    const waitThenRead = () => {
      const wait = POSTING_READS_MS[Math.min(reads, POSTING_READS_MS.length - 1)];
      timer = setTimeout(() => void read(), wait);
    };

    waitThenRead();
    return () => {
      stopped = true;
      clearTimeout(timer);
      document.removeEventListener('visibilitychange', read);
    };
  }, [reading, postId]);

  return posting;
}
