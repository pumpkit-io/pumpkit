import { Button } from '@/components/ui/button';
import { useBilling } from './useBilling';

/** Says what needs a Subscription and opens the Billing dialog; `source` tags the analytics. */
export function SubscribePrompt({ message, source }: { message: string; source: string }) {
  const billing = useBilling();
  return (
    <div className="flex flex-col gap-3 rounded-lg border border-border bg-muted/40 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
      <p className="font-sans text-sm text-foreground">{message}</p>
      <Button size="sm" className="h-10 shrink-0" onClick={() => billing.open(source)}>
        Subscribe
      </Button>
    </div>
  );
}
