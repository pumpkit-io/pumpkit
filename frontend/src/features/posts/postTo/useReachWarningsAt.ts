import { useEffect, useState } from 'react';
import { postService, type ReachWarning } from '@/services/postService';

/**
 * The Reach warnings for the Post's Text were it to go out at `publishAt`, or now for null. The
 * last list stays while the next is read, so the dialog doesn't flicker as the time changes; a
 * failed read shows none, since the last list may be for another time.
 */
export function useReachWarningsAt(postId: string, publishAt: string | null): ReachWarning[] {
  const [warnings, setWarnings] = useState<ReachWarning[]>([]);

  useEffect(() => {
    let live = true;
    postService
      .reachWarningsAt(postId, publishAt)
      .then((fresh) => {
        if (live) setWarnings(fresh);
      })
      .catch(() => {
        if (live) setWarnings([]);
      });
    return () => {
      live = false;
    };
  }, [postId, publishAt]);

  return warnings;
}
