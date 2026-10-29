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
}

/** Single post or Thread, as two radios drawn as one segmented control. */
export function FormatSelector({ value, onChange, disabled = false }: FormatSelectorProps) {
  const name = useId();
  const labelId = useId();

  return (
    <div className="space-y-1.5">
      <p id={labelId} className="font-sans text-sm font-medium text-foreground">
        Format
      </p>
      <div
        role="radiogroup"
        aria-labelledby={labelId}
        className="inline-flex rounded-lg bg-muted p-0.5"
      >
        {OPTIONS.map((option) => (
          <label
            key={option.format}
            className={cn(
              'cursor-pointer rounded-sm px-3 py-1.5 font-sans text-sm transition-colors motion-reduce:transition-none has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-ring',
              value === option.format
                ? 'bg-card font-medium text-foreground shadow-raised'
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
