import { useEffect } from 'react';

/** What each page that asks before leaving says, latest last. */
const asking: { message: string }[] = [];

/**
 * Whether to go ahead and leave the page: at once when no page asks first, else the User's
 * answer to the latest page's question. Every in-app way of leaving goes through it.
 */
export function confirmLeaving(): boolean {
  const latest = asking.at(-1);
  return latest === undefined || window.confirm(latest.message);
}

/**
 * While `active`, leaving the page asks first: closing or reloading the tab through the
 * browser's own prompt, and leaving within the app (a link, a shortcut, back or forward)
 * through `message`, once `ConfirmLeavingNavigation` is around the page.
 */
export function useConfirmLeaving(active: boolean, message: string) {
  useEffect(() => {
    if (!active) return;
    const entry = { message };
    asking.push(entry);
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      // Older browsers ask only when this is set.
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', onBeforeUnload);
    return () => {
      asking.splice(asking.indexOf(entry), 1);
      window.removeEventListener('beforeunload', onBeforeUnload);
    };
  }, [active, message]);
}
