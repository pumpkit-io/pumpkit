import { ImagePlus } from 'lucide-react';
import { useRef } from 'react';
import { HoverLabel, HoverLabels } from '@/features/posts/HoverLabel';
import { ICON_BUTTON } from '@/features/posts/panels/iconButton';
import { cn } from '@/lib/utils';
import { ACCEPTED_TYPES, PART_SAVING, X_MEDIA_RULE } from './mediaRules';

/**
 * The media button on a Part's counter row, where X's composer has it, opening the file picker
 * (the photo library on a phone). Once the Part is full, or while it is still `saving`, it stays
 * focusable, naming why it takes no files.
 */
export function MediaButton({
  where,
  full,
  saving = false,
  onFiles,
  onClickInsteadOfPicker,
}: {
  /** "Part 2", or "the post". */
  where: string;
  full: boolean;
  saving?: boolean;
  onFiles: (files: File[]) => void;
  /** Runs in place of the file picker, such as asking to reconnect X first. */
  onClickInsteadOfPicker?: () => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  const unavailable = saving || full;
  return (
    <HoverLabels>
      <HoverLabel label={saving ? PART_SAVING : full ? X_MEDIA_RULE : 'Add media'}>
        <button
          type="button"
          aria-label={`Add media to ${where}`}
          aria-disabled={unavailable || undefined}
          onClick={() => {
            if (unavailable) return;
            if (onClickInsteadOfPicker) onClickInsteadOfPicker();
            else input.current?.click();
          }}
          className={cn(
            ICON_BUTTON,
            '-my-1.5 shrink-0',
            unavailable && 'cursor-not-allowed opacity-50',
          )}
        >
          <ImagePlus aria-hidden className="h-[18px] w-[18px]" />
        </button>
      </HoverLabel>
      <input
        ref={input}
        type="file"
        aria-label={`Choose media for ${where}`}
        accept={ACCEPTED_TYPES.join(',')}
        multiple
        hidden
        onChange={(e) => {
          const files = Array.from(e.target.files ?? []);
          // Lets the same file be chosen again after it is removed.
          e.target.value = '';
          if (files.length) onFiles(files);
        }}
      />
    </HoverLabels>
  );
}
