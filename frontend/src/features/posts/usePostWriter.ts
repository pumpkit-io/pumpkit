import { useCallback, useState } from 'react';
import { useSubscribed } from '@/features/billing/useSubscribed';
import { track } from '@/lib/analytics';
import { timeOfDay } from '@/lib/relativeTime';
import { errorMessage, errorRetryAt, errorStatus } from '@/services/apiErrors';
import { postService, type Post } from '@/services/postService';

/** A 4xx: the backend turned the request down before writing anything, so no Version failed. */
function isRefusal(e: unknown): boolean {
  const status = errorStatus(e);
  return status !== null && status >= 400 && status < 500;
}

/** The Post on screen, which a reload doesn't restore: starting one from a Brief, then Feedback. */
export function usePostWriter() {
  const { refresh: refreshSubscribed } = useSubscribed();
  const [post, setPost] = useState<Post | null>(null);
  const [isWriting, setIsWriting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // The hourly limit on attempts: not an error, since trying again before `retry_at` won't help.
  const [notice, setNotice] = useState<string | null>(null);

  const fail = useCallback(
    (e: unknown, fallback: string) => {
      const retryAt = errorRetryAt(e);
      // A refusal for want of a Subscription shows the prompt to subscribe, not an error.
      if (errorStatus(e) === 403) refreshSubscribed();
      else if (retryAt)
        setNotice(`${errorMessage(e, fallback)} You can write again at ${timeOfDay(retryAt)}.`);
      else setError(errorMessage(e, fallback));
    },
    [refreshSubscribed],
  );

  /** Every call starts a new Post, a retry after a failure included. */
  const start = useCallback(
    async (brief: string) => {
      setIsWriting(true);
      setError(null);
      setNotice(null);
      track('post_version_requested', { kind: 'brief' });
      try {
        setPost(await postService.start(brief));
      } catch (e) {
        if (!isRefusal(e)) track('post_version_failed', { kind: 'brief' });
        fail(e, "Couldn't write the Post. Please try again.");
      } finally {
        setIsWriting(false);
      }
    },
    [fail],
  );

  /** Resolves true once the Version is on screen, so the caller can clear its Feedback box. */
  const addFeedback = useCallback(
    async (feedback: string): Promise<boolean> => {
      if (!post) return false;
      setIsWriting(true);
      setError(null);
      setNotice(null);
      track('post_version_requested', { kind: 'feedback' });
      try {
        const version = await postService.addVersion(post.id, feedback);
        setPost((current) =>
          current?.id === post.id
            ? { ...current, versions: [...current.versions, version] }
            : current,
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
    [post, fail],
  );

  const clear = useCallback(() => {
    setPost(null);
    setError(null);
    setNotice(null);
  }, []);

  return { post, isWriting, error, notice, start, addFeedback, clear };
}
