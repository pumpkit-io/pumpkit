import type { AllowanceUsage } from '@/services/usageService';
import { allowanceDay, isLow } from './usage';

const NOUNS = { generations: 'generations', xPosts: 'X posts' } as const;

/**
 * The quiet line under an action once less than a tenth of its count is left, such as "43
 * generations left until 14 November". Nothing while usage is unknown or there is no Allowance.
 */
export function LowUsageWarning({
  allowance,
  count,
}: {
  allowance: AllowanceUsage | null | undefined;
  count: keyof typeof NOUNS;
}) {
  if (!allowance || !isLow(allowance[count])) return null;
  return (
    <p className="font-sans text-xs text-muted-foreground">
      {`${allowance[count].left} ${NOUNS[count]} left until ${allowanceDay(allowance.resetsAt)}`}
    </p>
  );
}
