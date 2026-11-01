import { Link } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { PAYWALL_PATH } from '@/features/onboarding/paths';

/** Says what needs a Subscription and links to the Paywall, for a page outside its gate. */
export function SubscribePrompt({ message }: { message: string }) {
  return (
    <div className="flex flex-col gap-3 rounded-lg border border-border bg-muted/40 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
      <p className="font-sans text-sm text-foreground">{message}</p>
      <Button asChild size="sm" className="h-10 shrink-0">
        <Link to={PAYWALL_PATH}>Subscribe</Link>
      </Button>
    </div>
  );
}
