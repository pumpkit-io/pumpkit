import { useEffect } from 'react';

export const IS_MAC =
  typeof navigator !== 'undefined' && /Mac|iPod|iPhone|iPad/.test(navigator.platform);

export const MOD_LABEL = IS_MAC ? '⌘' : 'Ctrl';

export interface ShortcutHandlers {
  onNewPost: () => void;
  onEscape: () => void;
}

/** App-wide keys, live even while typing so New Post works from the Brief box. */
export function useShortcuts({ onNewPost, onEscape }: ShortcutHandlers): void {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const mod = IS_MAC ? e.metaKey : e.ctrlKey;
      if (mod && e.shiftKey && e.key.toLowerCase() === 'o') {
        e.preventDefault();
        onNewPost();
      } else if (e.key === 'Escape') {
        onEscape();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onNewPost, onEscape]);
}
