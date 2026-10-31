import { useState } from 'react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { track } from '@/lib/analytics';
import { formatPrice } from '@/lib/money';
import { redirectTo } from '@/lib/navigation';
import { errorMessage } from '@/services/apiErrors';
import { billingService, type TermsAcceptance, type TopUpOffer } from '@/services/billingService';
import { generationsAndXPosts } from './counts';
import { acceptsAll, NOTHING_ACCEPTED } from './termsAcceptance';
import { TermsAcceptanceFields } from './TermsAcceptanceFields';
import { useLoadedBilling } from './useBilling';

/** What a Top-up adds: "250 generations and 50 X posts, up to 5 with a link", leaving out a count with no cap. */
function packLine({ generations, xPosts, linkXPosts }: TopUpOffer): string {
  const counts = generationsAndXPosts(generations, xPosts);
  const links = xPosts === null || linkXPosts === null ? '' : `, up to ${linkXPosts} with a link`;
  return `${counts}${links}`;
}

function BuyTopUpDialog({
  open,
  offer,
  termsVersion,
  onClose,
}: {
  open: boolean;
  offer: TopUpOffer;
  /** Null where the Instance has no Terms to accept (ADR 0011). */
  termsVersion: string | null;
  onClose: () => void;
}) {
  const [acceptance, setAcceptance] = useState<TermsAcceptance>(NOTHING_ACCEPTED);
  const [paying, setPaying] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const price = formatPrice(offer.amount, offer.currency);
  const accepted = termsVersion === null || acceptsAll(acceptance);

  const pay = async () => {
    track('top_up_checkout_started');
    setPaying(true);
    setError(null);
    try {
      redirectTo(await billingService.startTopUpCheckout(termsVersion, acceptance));
    } catch (e) {
      setError(errorMessage(e, "Couldn't start checkout. Try again."));
      setPaying(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(next) => (next ? null : onClose())}>
      <DialogContent className="max-w-[520px] max-sm:h-fit">
        <DialogHeader>
          <DialogTitle className="font-sans text-base font-semibold tracking-tight">
            Buy a top-up
          </DialogTitle>
          <DialogDescription className="font-sans">
            {packLine(offer)}, for {price}. Lasts 12 months, used after your monthly allowance.
          </DialogDescription>
        </DialogHeader>
        {termsVersion !== null && (
          <TermsAcceptanceFields value={acceptance} onChange={setAcceptance} purchase="topUp" />
        )}
        {error && (
          <p role="alert" className="px-6 font-sans text-sm text-destructive">
            {error}
          </p>
        )}
        <DialogFooter className="justify-end gap-2">
          <Button variant="outline" className="h-10" onClick={onClose}>
            Cancel
          </Button>
          <Button className="h-10" disabled={!accepted || paying} onClick={() => void pay()}>
            {paying ? 'Redirecting…' : `Pay ${price}`}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/**
 * "Buy top-up, €10", which opens the Buy top-up dialog. Nothing until the Instance's Top-up
 * offer is known, and nothing where it sells none. Loads billing where Settings hasn't.
 */
export function BuyTopUpButton({ className }: { className?: string }) {
  const { data } = useLoadedBilling();
  const [open, setOpen] = useState(false);

  const offer = data?.topUp;
  if (!data || !offer) return null;
  return (
    <>
      <Button
        type="button"
        size="sm"
        variant="outline"
        className={className ?? 'h-8'}
        onClick={() => setOpen(true)}
      >
        Buy top-up, {formatPrice(offer.amount, offer.currency)}
      </Button>
      {/* Mounted only while open, so a reopened dialog starts with no box ticked. */}
      {open && (
        <BuyTopUpDialog
          open
          offer={offer}
          termsVersion={data.termsVersion}
          onClose={() => setOpen(false)}
        />
      )}
    </>
  );
}
