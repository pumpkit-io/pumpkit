import { useCallback, useState } from 'react';
import { useSubscribed } from '@/features/billing/useSubscribed';
import { track } from '@/lib/analytics';
import { errorMessage, errorStatus } from '@/services/apiErrors';
import { postService, type Post } from '@/services/postService';

/** The Post on screen, which a reload doesn't restore: starting one from a Brief, then Feedback. */
export function usePostWriter() {
  const { refresh: refreshSubscribed } = useSubscribed();
  const [post, setPost] = useState<Post | null>(null);
  const [isWriting, setIsWriting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  /** Every call starts a new Post, a retry after a failure included. */
  const start = useCallback(
    async (brief: string) => {
      setIsWriting(true);
      setError(null);
      track('post_version_requested', { kind: 'brief' });
      try {
        setPost(await postService.start(brief));
      } catch (e) {
        track('post_version_failed', { kind: 'brief' });
        // A refusal for want of a Subscription shows the prompt to subscribe, not an error.
        if (errorStatus(e) === 403) refreshSubscribed();
        else setError(errorMessage(e, "Couldn't write the Post. Please try again."));
      } finally {
        setIsWriting(false);
      }
    },
    [refreshSubscribed],
  );

  /** Resolves true once the Version is on screen, so the caller can clear its Feedback box. */
  const addFeedback = useCallback(
    async (feedback: string): Promise<boolean> => {
      if (!post) return false;
      setIsWriting(true);
      setError(null);
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
        track('post_version_failed', { kind: 'feedback' });
        if (errorStatus(e) === 403) refreshSubscribed();
        else setError(errorMessage(e, "Couldn't write the next Version. Please try again."));
        return false;
      } finally {
        setIsWriting(false);
      }
    },
    [post, refreshSubscribed],
  );

  const clear = useCallback(() => {
    setPost(null);
    setError(null);
  }, []);

  return { post, isWriting, error, start, addFeedback, clear };
}
