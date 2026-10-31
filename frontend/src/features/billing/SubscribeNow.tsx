import { useEffect, useState } from 'react';
import { showToast } from '@/components/Toaster';
import { Button, type ButtonProps } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { track } from '@/lib/analytics';
import { formatAmount } from '@/lib/money';
import { errorMessage } from '@/services/apiErrors';
import { billingService, type OfferedAllowance, type Plan } from '@/services/billingService';
import type { BillingData } from './BillingProvider';
import { useBilling } from './useBilling';

/** "month", "3 months", "year": how long the first charge pays for. */
function firstPeriod({ interval, intervalCount }: Plan): string {
  return intervalCount === 1 ? interval : `${intervalCount} ${interval}s`;
}

/** "500 generations and 100 X posts", leaving out a count with no cap. */
function allowanceCounts({ generations, xPosts }: OfferedAllowance): string {
  return [
    generations !== null && `${generations} generations`,
    xPosts !== null && `${xPosts} X posts`,
  ]
    .filter(Boolean)
    .join(' and ');
}

function explanation(data: BillingData): string {
  const planKey = data.me.subscription?.planKey;
  const plan = data.plans.find((p) => p.key === planKey);
  const charge = plan
    ? `you're charged ${formatAmount(plan.amount, plan.currency)} today for your first ${firstPeriod(plan)}`
    : "you're charged for your plan today";
  const counts = allowanceCounts(data.allowance);
  const allowance = counts
    ? `Your monthly allowance of ${counts} starts at once.`
    : 'Your monthly allowance starts at once.';
  return `Your trial ends now and ${charge}. ${allowance}`;
}

/** Asks before ending the Trial, with the Plan's price, and ends it on confirm. */
function SubscribeNowDialog({
  open,
  onOpenChange,
  onSubscribed,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSubscribed?: () => void;
}) {
  const { data, isLoading, load } = useBilling();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Away from Settings, billing hasn't been loaded yet.
  useEffect(() => {
    if (open && !data && !isLoading) void load();
  }, [open, data, isLoading, load]);

  const confirm = async () => {
    setBusy(true);
    setError(null);
    try {
      await billingService.subscribeNow();
      track('billing_subscribe_now_confirmed');
      showToast('Subscribed. Your monthly allowance has started.');
      onOpenChange(false);
      onSubscribed?.();
    } catch (e) {
      setError(errorMessage(e, "Couldn't subscribe. Try again."));
    } finally {
      setBusy(false);
      // A failed charge still ends the Trial, so the Subscription changed either way.
      void load();
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) setError(null);
        onOpenChange(next);
      }}
    >
      <DialogContent className="max-w-[480px] max-sm:h-fit">
        <DialogHeader>
          <DialogTitle className="font-sans text-base font-semibold tracking-tight">
            Subscribe now
          </DialogTitle>
          <DialogDescription className="font-sans">
            {data ? explanation(data) : 'Loading the price…'}
          </DialogDescription>
        </DialogHeader>
        {error && (
          <p role="alert" className="px-6 font-sans text-sm text-destructive">
            {error}
          </p>
        )}
        <DialogFooter className="justify-end gap-2">
          <Button variant="outline" className="h-10" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button className="h-10" disabled={!data || busy} onClick={() => void confirm()}>
            Subscribe now
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** Subscribe now during a Trial: the button and the dialog it opens. */
export function SubscribeNowButton({
  onSubscribed,
  ...button
}: { onSubscribed?: () => void } & Pick<ButtonProps, 'size' | 'variant' | 'className'>) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button type="button" {...button} onClick={() => setOpen(true)}>
        Subscribe now
      </Button>
      <SubscribeNowDialog open={open} onOpenChange={setOpen} onSubscribed={onSubscribed} />
    </>
  );
}
