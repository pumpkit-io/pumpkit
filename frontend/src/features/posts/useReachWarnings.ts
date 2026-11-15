import { useEffect, useState } from 'react';
import { postService, type ReachWarning } from '@/services/postService';

/**
 * The Post's Reach warnings, read again whenever `source`, what the server works them out from,
 * changes to a saved text; null while that text isn't saved yet keeps the last ones.
 */
export function useReachWarnings(
  postId: string,
  read: ReachWarning[],
  source: string | null,
): ReachWarning[] {
  const [warnings, setWarnings] = useState(read);
  const [readFor, setReadFor] = useState(source);
  const [readPost, setReadPost] = useState(postId);
  if (readPost !== postId) {
    setReadPost(postId);
    setWarnings(read);
    setReadFor(source);
  }
  const stale = source !== null && source !== readFor;

  useEffect(() => {
    if (!stale) return;
    let live = true;
    postService
      .reachWarnings(postId)
      .then((fresh) => {
        if (!live) return;
        setWarnings(fresh);
        setReadFor(source);
      })
      // A missed warning costs less than an error on the page, so a failed read keeps the last.
      .catch(() => {});
    return () => {
      live = false;
    };
  }, [stale, postId, source]);

  return warnings;
}
