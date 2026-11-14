import { useEffect, useState } from 'react';
import { errorStatus } from '@/services/apiErrors';
import { pollDelay } from '@/services/postService';

/**
 * Calls `read` again after `delay` while `writing`, handing each answer to `onRead`. Reading
 * stops when the page closes and on a 404 or 403, which goes to `onGone`; any other failed read
 * waits longer before the next. `read`, `onRead`, `onGone` and `delay` must be stable.
 */
export function useReadWhileWriting<T>(
  writing: boolean,
  read: () => Promise<T>,
  onRead: (value: T) => void,
  onGone: (e: unknown) => void,
  delay: (failures: number) => number = pollDelay,
) {
  const [poll, setPoll] = useState({ count: 0, failures: 0 });
  useEffect(() => {
    if (!writing) return;
    let stopped = false;
    const timer = setTimeout(() => {
      read().then(
        (value) => {
          if (stopped) return;
          setPoll(({ count }) => ({ count: count + 1, failures: 0 }));
          onRead(value);
        },
        (e: unknown) => {
          if (stopped) return;
          const status = errorStatus(e);
          if (status === 404 || status === 403) onGone(e);
          else setPoll(({ count, failures }) => ({ count: count + 1, failures: failures + 1 }));
        },
      );
    }, delay(poll.failures));
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [writing, poll, read, onRead, onGone, delay]);
}
