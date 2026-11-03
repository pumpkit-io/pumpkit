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

/**
 * Turns back a history move the User declines. Added at module load, to run before BrowserRouter's.
 * The pop that turns a move back lands on the shown entry, so it passes without asking.
 */
function onPopState(event: PopStateEvent) {
  const to = entryIndex(event.state);
  if (to === null || shownIndex === null || to === shownIndex || confirmLeaving()) return;
  event.stopImmediatePropagation();
  window.history.go(shownIndex - to);
}

if (typeof window !== 'undefined') window.addEventListener('popstate', onPopState);

/**
 * Makes every in-app navigation below it go through `confirmLeaving`: links, `navigate()` and
 * the browser's back and forward. The app's BrowserRouter has no blocker, so this wraps its
 * navigator's push and replace; `navigate(-1)` pops, so the popstate listener asks for it.
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
    });
    return { ...navigation, navigator: wrapped };
  }, [navigation]);

  return (
    <UNSAFE_NavigationContext.Provider value={guarded}>
      {children}
    </UNSAFE_NavigationContext.Provider>
  );
}
