import { Button } from '@/components/ui/button';
import { formatAmount } from '@/lib/money';

interface ProductCardProps {
  title: string;
  description?: string | null;
  priceLabel: string;
  actionLabel: string;
  ariaLabel: string;
  disabled?: boolean;
  onAction: () => void;
}

export function ProductCard({ title, description, priceLabel, actionLabel, ariaLabel, disabled, onAction }: ProductCardProps) {
  return (
    <div className="flex flex-col gap-3 rounded-xl border border-border bg-card p-4">
      <div>
        <div className="font-sans text-sm font-semibold text-foreground">{title}</div>
        {description && <div className="mt-1 font-sans text-xs text-muted-foreground">{description}</div>}
      </div>
      <div className="font-sans text-lg font-semibold text-foreground">{priceLabel}</div>
      <Button type="button" size="sm" onClick={onAction} disabled={disabled} aria-label={ariaLabel}>
        {actionLabel}
      </Button>
    </div>
  );
}

export function recurringLabel(unitAmount: number | null, currency: string, interval: string, count: number): string {
  if (unitAmount == null) return 'Custom';
  const every = count === 1 ? interval : `${count} ${interval}s`;
  return `${formatAmount(unitAmount, currency)} / ${every}`;
}
