import { useCallback, useEffect, useRef, useState } from 'react';
import { useXConnectionContext } from '@/features/xConnection/useXConnectionContext';
import { errorStatus } from '@/services/apiErrors';
import { isUnwritten, postService } from '@/services/postService';
import type { ScheduledPost } from '@/services/scheduledPostService';

/** The waits between reads of a posting Post, the last one repeating for as long as it posts. */
export const POSTING_READS_MS = [3_000, 5_000, 10_000, 20_000, 30_000];
// A day covers any open page; setTimeout itself would fire at once past about 24.8 days.
const LONGEST_WAIT_MS = 24 * 60 * 60 * 1000;

/** Whether a read says what the shown Scheduled post says. */
function readsTheSame(read: ScheduledPost | null, shown: ScheduledPost | null) {
  return (
    read?.id === shown?.id &&
    read?.state === shown?.state &&
    read?.publishAt === shown?.publishAt &&
    read?.posting === shown?.posting
  );
}

type Waiting = Pick<ScheduledPost, 'id' | 'state' | 'publishAt' | 'posting'>;

/**
 * Posting as the server answered, or since its time came while the page sat open, for as long as
 * the same Scheduled post keeps the same time; `forget` drops that flip once a read answers anew.
 */
function useCameDue(scheduledPost: Waiting | null) {
  const [cameDue, setCameDue] = useState<string | null>(null);
  const id = scheduledPost?.id;
  const state = scheduledPost?.state;
  const publishAt = scheduledPost?.publishAt;
  const moment = id === undefined ? null : `${id} ${publishAt}`;

  useEffect(() => {
    if (state !== 'scheduled' || publishAt === undefined) return;
    const wait = Date.parse(publishAt) - Date.now();
    if (wait <= 0 || wait > LONGEST_WAIT_MS) return;
    const timer = setTimeout(() => setCameDue(moment), wait);
    return () => clearTimeout(timer);
  }, [moment, state, publishAt]);

  const forget = useCallback(() => setCameDue(null), []);
  const posting =
    !!scheduledPost && (scheduledPost.posting || (state === 'scheduled' && cameDue === moment));
  return { posting, forget };
}

/** Whether the Scheduled post is posting, by the server or since its time came on this page. */
export function useIsPosting(scheduledPost: Waiting | null): boolean {
  return useCameDue(scheduledPost).posting;
}

/**
 * `useIsPosting`, reading the Post while posting or waiting for a retry, less often over time and
 * only while the tab is visible; passes changes to `onChange`, reloading X's connection on Failed.
 */
export function usePosting(
  postId: string,
  scheduledPost: ScheduledPost | null,
  onChange: (scheduledPost: ScheduledPost | null) => void,
  onGone: () => void,
): boolean {
  const { posting, forget } = useCameDue(scheduledPost);
  const { reload: reloadXConnection } = useXConnectionContext();
  const retrying =
    scheduledPost?.state === 'scheduled' &&
    !posting &&
    Date.parse(scheduledPost.publishAt) <= Date.now();
  const reading = posting || retrying;

  const latest = useRef({ scheduledPost, onChange, onGone, forget, reloadXConnection });
  latest.current = { scheduledPost, onChange, onGone, forget, reloadXConnection };

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
        const post = await postService.get(postId);
        const current = isUnwritten(post) ? null : post.scheduledPost;
        if (stopped) return;
        const shown = latest.current;
        shown.forget();
        if (!readsTheSame(current, shown.scheduledPost)) {
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
