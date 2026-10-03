import { useEffect, useRef, type RefObject } from 'react';

export function useOnceVisible(
  ref: RefObject<Element | null>,
  onVisible: () => void,
  options: IntersectionObserverInit = { threshold: 0.3 },
): void {
  const callbackRef = useRef(onVisible);
  callbackRef.current = onVisible;

  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    if (typeof IntersectionObserver === 'undefined') {
      callbackRef.current();
      return;
    }

    const observer = new IntersectionObserver((entries) => {
      for (const entry of entries) {
        if (entry.isIntersecting) {
          callbackRef.current();
          observer.disconnect();
          return;
        }
      }
    }, options);
    observer.observe(node);
    return () => observer.disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ref]);
}
