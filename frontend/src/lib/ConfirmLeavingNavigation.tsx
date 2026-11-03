import { useContext, useEffect, useMemo, useRef, type ReactNode } from 'react';
import { UNSAFE_NavigationContext, useLocation, type Navigator, type To } from 'react-router-dom';
import { confirmLeaving } from './useConfirmLeaving';

/** The history entry's place, which React Router's BrowserRouter keeps in its state. */
function entryIndex(state: unknown): number | null {
  const idx = (state as { idx?: unknown } | null)?.idx;
  return typeof idx === 'number' ? idx : null;
}

function pathnameOf(to: To, from: string): string {
  if (typeof to === 'string') return new URL(to, new URL(from, window.location.origin)).pathname;
  return to.pathname ?? from;
}

/** The history entry the mounted guard shows, or null with no guard mounted. */
let shownIndex: number | null = null;
let restoring = false;

/**
 * Turns back a history move the User declines. Added as the module loads, so it runs before
 * React Router's own popstate listener, which BrowserRouter adds once it mounts.
 */
function onPopState(event: PopStateEvent) {
  if (restoring) {
    restoring = false;
    event.stopImmediatePropagation();
    return;
  }
  const to = entryIndex(event.state);
  if (to === null || shownIndex === null || confirmLeaving()) return;
  event.stopImmediatePropagation();
  restoring = true;
  window.history.go(shownIndex - to);
}

if (typeof window !== 'undefined') window.addEventListener('popstate', onPopState);

/**
 * Makes every in-app navigation below it go through `confirmLeaving`: links, `navigate()` and
 * the browser's back and forward. The app's BrowserRouter has no blocker, so this wraps its
 * navigator, and tells the popstate listener which entry to go back to.
 */
export function ConfirmLeavingNavigation({ children }: { children: ReactNode }) {
  const navigation = useContext(UNSAFE_NavigationContext);
  const location = useLocation();
  const shownPathname = useRef(location.pathname);

  useEffect(() => {
    shownIndex = entryIndex(window.history.state);
    shownPathname.current = location.pathname;
  }, [location]);

  useEffect(
    () => () => {
      shownIndex = null;
    },
    [],
  );

  const guarded = useMemo(() => {
    const { navigator } = navigation;
    const leaves = (to: To) => {
      const from = shownPathname.current;
      return pathnameOf(to, from) !== from && !confirmLeaving();
    };
    const wrapped: Navigator = Object.assign(Object.create(navigator) as Navigator, {
      push: (to: To, ...rest: unknown[]) => {
        if (leaves(to)) return;
        (navigator.push as (to: To, ...rest: unknown[]) => void)(to, ...rest);
      },
      replace: (to: To, ...rest: unknown[]) => {
        if (leaves(to)) return;
        (navigator.replace as (to: To, ...rest: unknown[]) => void)(to, ...rest);
      },
      go: (delta: number) => {
        if (delta !== 0 && !confirmLeaving()) return;
        navigator.go(delta);
      },
    });
    return { ...navigation, navigator: wrapped };
  }, [navigation]);

  return (
    <UNSAFE_NavigationContext.Provider value={guarded}>
      {children}
    </UNSAFE_NavigationContext.Provider>
  );
}
