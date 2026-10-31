import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { track } from '@/lib/analytics';
import { redirectTo } from '@/lib/navigation';
import { billingService } from '@/services/billingService';
import { errorMessage, type AllowanceUsedUp } from '@/services/apiErrors';
import { BuyTopUpButton } from './BuyTopUp';

/**
 * The Allowance refusal where the User acted, in place of the action's error banner, with the
 * way out the backend offers. Way outs without a flow yet (subscribe now) show nothing.
 */
export function AllowanceNotice({ refusal }: { refusal: AllowanceUsedUp }) {
  const [error, setError] = useState<string | null>(null);

  const openPortal = async () => {
    setError(null);
    try {
      const url = await billingService.openBillingPortal();
      track('billing_portal_opened');
      redirectTo(url);
    } catch (e) {
      setError(errorMessage(e, "Couldn't open the billing portal. Try again."));
    }
  };

  return (
    <div
      role="status"
      className="space-y-2 rounded-md border border-border bg-muted px-3 py-2 font-sans text-xs text-foreground"
    >
      <p>{refusal.message}</p>
      {refusal.wayOut === 'update_payment' && (
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="h-8"
          onClick={() => void openPortal()}
        >
          Update your payment method
        </Button>
      )}
      {refusal.wayOut === 'top_up' && <BuyTopUpButton />}
      {error && <p className="text-destructive">{error}</p>}
    </div>
  );
}
