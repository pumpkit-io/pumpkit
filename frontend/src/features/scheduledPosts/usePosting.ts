import { useEffect, useRef, useState } from 'react';
import { postService } from '@/services/postService';
import type { ScheduledPost } from '@/services/scheduledPostService';

/** The waits between reads of a posting Post, the last one repeating for as long as it posts. */
export const POSTING_READS_MS = [3_000, 5_000, 10_000, 20_000, 30_000];
// A day covers any open page; setTimeout itself would fire at once past about 24.8 days.
const LONGEST_WAIT_MS = 24 * 60 * 60 * 1000;

function sameScheduledPost(a: ScheduledPost | null, b: ScheduledPost | null): boolean {
  return a?.id === b?.id && a?.state === b?.state && a?.publishAt === b?.publishAt;
}

/**
 * Whether the Scheduled post is posting: claimed by a publish, or due and waiting for the
 * publisher, as Post now with a GIF or a video leaves it. While it is, reads the Post again,
 * less and less often and only while the tab is visible, and passes on each change of its
 * Scheduled post to `onChange`, until it is Published or Failed.
 */
export function usePosting(
  postId: string,
  scheduledPost: ScheduledPost | null,
  onChange: (scheduledPost: ScheduledPost | null) => void,
): boolean {
  const [now, setNow] = useState(() => Date.now());
  const state = scheduledPost?.state ?? null;
  const publishAt = scheduledPost ? Date.parse(scheduledPost.publishAt) : null;
  const posting =
    state === 'publishing' || (state === 'scheduled' && publishAt !== null && publishAt <= now);

  const latest = useRef({ scheduledPost, onChange });
  latest.current = { scheduledPost, onChange };

  useEffect(() => {
    if (state !== 'scheduled' || publishAt === null) return;
    const wait = publishAt - Date.now();
    if (wait <= 0) {
      setNow(Date.now());
      return;
    }
    if (wait > LONGEST_WAIT_MS) return;
    const timer = setTimeout(() => setNow(Date.now()), wait);
    return () => clearTimeout(timer);
  }, [state, publishAt]);

  useEffect(() => {
    if (!posting) return;
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
        if (!sameScheduledPost(current, latest.current.scheduledPost))
          latest.current.onChange(current);
      } catch {
        // A failed read is tried again at the next wait.
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
  }, [posting, postId]);

  return posting;
}
