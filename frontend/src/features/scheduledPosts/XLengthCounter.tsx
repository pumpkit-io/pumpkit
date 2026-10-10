import { formatCount } from '@/lib/characters';
import { cn } from '@/lib/utils';

/** The length by X's count against the X connection's limit, always shown: X enforces it. */
export function XLengthCounter({ length, limit }: { length: number; limit: number }) {
  const over = length - limit;
  return (
    <p
      className={cn(
        'font-sans text-xs tabular-nums',
        over > 0 ? 'font-medium text-red-700 dark:text-red-300' : 'text-muted-foreground',
      )}
    >
      {over > 0
        ? `${formatCount(over)} ${over === 1 ? 'character' : 'characters'} over the ${formatCount(limit)} limit`
        : `${formatCount(length)} / ${formatCount(limit)}`}
    </p>
  );
}
