import { formatCount } from '@/lib/characters';
import { cn } from '@/lib/utils';

/** A Part's length against the account's limit, "612 / 700", in the warning colour when over. */
export function CharacterCount({
  count,
  limit,
  className,
}: {
  count: number;
  limit: number;
  className?: string;
}) {
  return (
    <p
      className={cn(
        'font-mono tabular-nums',
        count > limit ? 'text-destructive' : 'text-muted-foreground',
        className,
      )}
    >
      {formatCount(count)} / {formatCount(limit)}
    </p>
  );
}
