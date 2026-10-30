import { useId } from 'react';
import { cn } from '@/lib/utils';
import type { Format } from '@/services/postService';

const OPTIONS: { format: Format; label: string }[] = [
  { format: 'post', label: 'Single post' },
  { format: 'thread', label: 'Thread' },
];

interface FormatSelectorProps {
  value: Format;
  onChange: (format: Format) => void;
  disabled?: boolean;
  /** Names the toggle "Format" for screen readers only, where it sits inside a composer. */
  hideLabel?: boolean;
}

/** Single post or Thread, as two radios drawn as one segmented control with a sliding thumb. */
export function FormatSelector({
  value,
  onChange,
  disabled = false,
  hideLabel = false,
}: FormatSelectorProps) {
  const name = useId();
  const labelId = useId();

  return (
    <div className={cn(!hideLabel && 'space-y-1.5')}>
      {!hideLabel && (
        <p id={labelId} className="font-sans text-sm font-medium text-foreground">
          Format
        </p>
      )}
      <div
        role="radiogroup"
        aria-label={hideLabel ? 'Format' : undefined}
        aria-labelledby={hideLabel ? undefined : labelId}
        className="relative inline-grid grid-cols-2 rounded-lg bg-muted p-0.5"
      >
        {/* One thumb slides under both options, so a change shows which way it went. */}
        <span
          aria-hidden
          className={cn(
            'absolute inset-y-0.5 left-0.5 w-[calc(50%-2px)] rounded-sm bg-card shadow-raised transition-transform duration-200 ease-out motion-reduce:transition-none',
            value === 'thread' && 'translate-x-full',
            disabled && 'opacity-50',
          )}
        />
        {OPTIONS.map((option) => (
          <label
            key={option.format}
            // The press keeps focus where it is, so focus goes straight to the radio on release
            // and a composer around the toggle never shows a moment without its focus line.
            onMouseDown={(e) => e.preventDefault()}
            className={cn(
              'relative cursor-pointer rounded-sm px-3 py-1.5 text-center font-sans text-sm transition-colors duration-200 motion-reduce:transition-none has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-ring',
              value === option.format
                ? 'font-medium text-foreground'
                : 'text-muted-foreground hover:text-foreground',
              disabled && 'cursor-not-allowed opacity-50',
            )}
          >
            <input
              type="radio"
              name={name}
              value={option.format}
              checked={value === option.format}
              onChange={() => onChange(option.format)}
              disabled={disabled}
              className="sr-only"
            />
            {option.label}
          </label>
        ))}
      </div>
    </div>
  );
}
