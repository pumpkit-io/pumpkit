import { useEffect } from 'react';

/** Whether a click follows a link to another page of the app in this tab. */
function inAppLink(event: MouseEvent): boolean {
  if (event.defaultPrevented || event.button !== 0) return false;
  if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return false;
  const link = event.target instanceof Element ? event.target.closest('a[href]') : null;
  if (!(link instanceof HTMLAnchorElement)) return false;
  if ((link.target && link.target !== '_self') || link.hasAttribute('download')) return false;
  return link.origin === window.location.origin;
}

/**
 * While `active`, leaving the page asks first: closing or reloading the tab through the
 * browser's own prompt, and following a link in the app through `message`. The app's
 * BrowserRouter has no navigation blocker, so the browser's back and forward go unasked.
 */
export function useConfirmLeaving(active: boolean, message: string) {
  useEffect(() => {
    if (!active) return;
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      // Older browsers ask only when this is set.
      event.returnValue = '';
    };
    // Capturing on the document runs before React Router's own click handlers on the link.
    const onClick = (event: MouseEvent) => {
      if (!inAppLink(event) || window.confirm(message)) return;
      event.preventDefault();
      event.stopPropagation();
    };
    window.addEventListener('beforeunload', onBeforeUnload);
    document.addEventListener('click', onClick, true);
    return () => {
      window.removeEventListener('beforeunload', onBeforeUnload);
      document.removeEventListener('click', onClick, true);
    };
  }, [active, message]);
}
