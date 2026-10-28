import { useCallback, useEffect, useState } from 'react';
import { track } from '@/lib/analytics';
import { errorMessage, errorStatus } from '@/services/apiErrors';
import { postService, type Format, type PostDetail } from '@/services/postService';
import type { ScheduledPost } from '@/services/scheduledPostService';
import { statusFrom } from './postStatus';
import { usePostCounts } from './usePostCounts';
import { isRefusal, useWritingFailure } from './useWritingFailure';

export type PostLoad =
  | { kind: 'loading' }
  | { kind: 'loaded'; post: PostDetail }
  | { kind: 'notFound' }
  | { kind: 'failed'; message: string };

/**
 * One Post as the server has it, with Feedback on it. After an action that changes its
 * Scheduled post, pass the answer to `setScheduledPost` (null once deleted): the status follows,
 * and so do the Post counts behind the sidebar's Failed badge.
 */
export function usePost(postId: string) {
  const [load, setLoad] = useState<PostLoad>({ kind: 'loading' });
  const [isWriting, setIsWriting] = useState(false);
  const writing = useWritingFailure();
  const { fail, clear } = writing;
  const { refresh: refreshCounts } = usePostCounts();

  const reload = useCallback(async () => {
    setLoad({ kind: 'loading' });
    try {
      setLoad({ kind: 'loaded', post: await postService.get(postId) });
    } catch (e) {
      if (errorStatus(e) === 404) setLoad({ kind: 'notFound' });
      else setLoad({ kind: 'failed', message: errorMessage(e, "Couldn't load the Post.") });
    }
  }, [postId]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const update = useCallback((change: (post: PostDetail) => PostDetail) => {
    setLoad((current) =>
      current.kind === 'loaded' ? { kind: 'loaded', post: change(current.post) } : current,
    );
  }, []);

  const setScheduledPost = useCallback(
    (scheduledPost: ScheduledPost | null) => {
      update((post) => ({
        ...post,
        scheduledPost,
        status: statusFrom(scheduledPost?.state ?? null),
      }));
      refreshCounts();
    },
    [update, refreshCounts],
  );

  /** Resolves true once the new Version is in the Post, so the caller can clear its box. */
  const addFeedback = useCallback(
    async (feedback: string, format: Format): Promise<boolean> => {
      setIsWriting(true);
      clear();
      track('post_version_requested', { kind: 'feedback' });
      try {
        const version = await postService.addVersion(postId, feedback, format);
        update((post) =>
          post.id === postId ? { ...post, versions: [...post.versions, version] } : post,
        );
        return true;
      } catch (e) {
        if (!isRefusal(e)) track('post_version_failed', { kind: 'feedback' });
        fail(e, "Couldn't write the next Version. Please try again.");
        return false;
      } finally {
        setIsWriting(false);
      }
    },
    [postId, clear, fail, update],
  );

  return {
    load,
    reload,
    setScheduledPost,
    addFeedback,
    isWriting,
    error: writing.error,
    notice: writing.notice,
  };
}
