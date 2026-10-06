import { Button } from '@/components/ui/button';
import { formatAmount } from '@/lib/money';

interface PlanCardProps {
  title: string;
  priceLabel: string;
  /** A short line under the price, e.g. the free Trial. */
  note?: string;
  actionLabel: string;
  ariaLabel: string;
  disabled?: boolean;
  onAction: () => void;
}

export function PlanCard({
  title,
  priceLabel,
  note,
  actionLabel,
  ariaLabel,
  disabled,
  onAction,
}: PlanCardProps) {
  return (
    <div className="flex flex-col gap-3 rounded-xl border border-border bg-card p-4">
      <div>
        <div className="font-sans text-sm font-semibold text-foreground">{title}</div>
      </div>
      <div className="font-sans text-lg font-semibold text-foreground">{priceLabel}</div>
      {note && <div className="font-sans text-xs text-muted-foreground">{note}</div>}
      <Button type="button" size="sm" onClick={onAction} disabled={disabled} aria-label={ariaLabel}>
        {actionLabel}
      </Button>
    </div>
  );
}

/** A Plan's price, e.g. "€9.00 / month" or "€24.00 / 3 months". */
export function recurringLabel(
  amount: number,
  currency: string,
  interval: string,
  count: number,
): string {
  const every = count === 1 ? interval : `${count} ${interval}s`;
  return `${formatAmount(amount, currency)} / ${every}`;
}
