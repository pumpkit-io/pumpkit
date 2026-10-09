import { useEffect } from 'react';

export const IS_MAC =
  typeof navigator !== 'undefined' && /Mac|iPod|iPhone|iPad/.test(navigator.platform);

export const MOD_LABEL = IS_MAC ? '⌘' : 'Ctrl';

export const NEW_POST_KEYS = { key: 'o', label: `${MOD_LABEL}⇧O` };

const isNewPost = (e: KeyboardEvent) =>
  (IS_MAC ? e.metaKey : e.ctrlKey) && e.shiftKey && e.key.toLowerCase() === NEW_POST_KEYS.key;

export interface ShortcutHandlers {
  onNewPost: () => void;
  onEscape: () => void;
}

/** App-wide keys, live even while typing so New Post works from the Brief box. */
export function useShortcuts({ onNewPost, onEscape }: ShortcutHandlers): void {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (isNewPost(e)) {
        e.preventDefault();
        // An open dialog hides the writer, so a New Post there would clear it out of sight.
        if (!e.repeat && !document.querySelector('[role="dialog"]')) onNewPost();
      } else if (e.key === 'Escape') {
        onEscape();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onNewPost, onEscape]);
}
