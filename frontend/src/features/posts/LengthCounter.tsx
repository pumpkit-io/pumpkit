import { formatCount } from '@/lib/characters';
import { cn } from '@/lib/utils';

// The limits guard against abuse, so the counter stays out of the way until the text nears one.
const SHOWN_WITHIN = 10_000;

export function LengthCounter({ length, max }: { length: number; max: number }) {
  if (length < max - SHOWN_WITHIN) return null;
  const over = length - max;
  return (
    <p
      className={cn(
        'font-sans text-xs tabular-nums',
        over > 0 ? 'font-medium text-red-700 dark:text-red-300' : 'text-muted-foreground',
      )}
    >
      {over > 0
        ? `${formatCount(over)} characters over the ${formatCount(max)} limit`
        : `${formatCount(length)} / ${formatCount(max)} characters`}
    </p>
  );
}
