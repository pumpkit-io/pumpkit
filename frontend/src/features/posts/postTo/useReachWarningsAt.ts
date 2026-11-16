import { useEffect, useState } from 'react';
import { postService, type ReachWarning } from '@/services/postService';

/**
 * The Reach warnings for the Post's Text were it to go out at `publishAt`, or now for null. The
 * last list stays until the next arrives, so the dialog doesn't flicker as the time changes.
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
      // A missed warning costs less than a broken dialog.
      .catch(() => {
        if (live) setWarnings([]);
      });
    return () => {
      live = false;
    };
  }, [postId, publishAt]);

  return warnings;
}
