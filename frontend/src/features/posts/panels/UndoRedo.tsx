import { Redo2, Undo2 } from 'lucide-react';
import { IS_MAC } from '@/lib/shortcuts';
import { cn } from '@/lib/utils';
import { ICON_BUTTON } from './iconButton';

const UNDO_KEYS = IS_MAC ? '⌘Z' : 'Ctrl+Z';
const REDO_KEYS = IS_MAC ? '⇧⌘Z' : 'Ctrl+Shift+Z';

/** The dock's undo and redo, each disabled at its end of the undo line. */
export function UndoRedo({ onUndo, onRedo }: { onUndo?: () => void; onRedo?: () => void }) {
  return (
    <>
      <button
        type="button"
        aria-label="Undo"
        title={`Undo (${UNDO_KEYS})`}
        disabled={!onUndo}
        onClick={onUndo}
        className={cn(ICON_BUTTON, '-my-1')}
      >
        <Undo2 aria-hidden className="h-4 w-4" />
      </button>
      <button
        type="button"
        aria-label="Redo"
        title={`Redo (${REDO_KEYS})`}
        disabled={!onRedo}
        onClick={onRedo}
        className={cn(ICON_BUTTON, '-my-1')}
      >
        <Redo2 aria-hidden className="h-4 w-4" />
      </button>
    </>
  );
}
