import { Redo2, Undo2 } from 'lucide-react';
import { cn } from '@/lib/utils';
import { HoverLabel } from './HoverLabel';
import { ICON_BUTTON } from './iconButton';

/** The Post card's undo and redo, each disabled at its end of the undo line. */
export function UndoRedo({ onUndo, onRedo }: { onUndo?: () => void; onRedo?: () => void }) {
  return (
    <>
      <HoverLabel label="Undo edit">
        <button
          type="button"
          aria-label="Undo"
          disabled={!onUndo}
          onClick={onUndo}
          className={cn(ICON_BUTTON, '-my-1')}
        >
          <Undo2 aria-hidden className="h-4 w-4" />
        </button>
      </HoverLabel>
      <HoverLabel label="Redo edit">
        <button
          type="button"
          aria-label="Redo"
          disabled={!onRedo}
          onClick={onRedo}
          className={cn(ICON_BUTTON, '-my-1')}
        >
          <Redo2 aria-hidden className="h-4 w-4" />
        </button>
      </HoverLabel>
    </>
  );
}
