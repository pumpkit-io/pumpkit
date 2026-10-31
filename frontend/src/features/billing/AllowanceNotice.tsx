import { useState } from 'react';
import { Button } from '@/components/ui/button';
import type { AllowanceUsedUp } from '@/services/apiErrors';
import { BuyTopUpButton } from './BuyTopUp';
import { SubscribeNowButton } from './SubscribeNow';
import { useOpenPortal } from './useOpenPortal';

/**
 * The Allowance refusal where the User acted, in place of the action's error banner, with the
 * way out the backend offers. Once the User subscribes now the refusal no longer holds, so the
 * notice goes.
 */
export function AllowanceNotice({ refusal }: { refusal: AllowanceUsedUp }) {
  const { openPortal, error } = useOpenPortal();
  const [subscribed, setSubscribed] = useState(false);

  if (subscribed) return null;
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
      {refusal.wayOut === 'subscribe_now' && (
        <SubscribeNowButton size="sm" className="h-8" onSubscribed={() => setSubscribed(true)} />
      )}
      {error && <p className="text-destructive">{error}</p>}
    </div>
  );
}
