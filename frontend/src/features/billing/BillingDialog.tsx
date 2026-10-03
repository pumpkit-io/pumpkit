import { useState } from 'react';
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { billingService, errorMessage } from '@/services/billingService';
import { formatAmount } from '@/lib/money';
import { redirectTo } from '@/lib/navigation';
import { track } from '@/lib/analytics';
import { useBilling } from './useBilling';
import { ProductCard, recurringLabel } from './ProductCard';

const STATUS_LABEL: Record<string, string> = {
  pending: 'Pending',
  paid: 'Paid',
  refunded: 'Refunded',
  partially_refunded: 'Partially refunded',
  disputed: 'Disputed',
  failed: 'Failed',
};

function ErrorBanner({ message }: { message: string }) {
  return (
    <div role="alert" aria-live="polite" className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 font-sans text-xs text-destructive">
      {message}
    </div>
  );
}

export function BillingDialog() {
  const { isOpen, close, error, openWithError, data, isLoading } = useBilling();
  const [pendingId, setPendingId] = useState<string | null>(null);

  const go = async (id: string, start: () => Promise<string>) => {
    setPendingId(id);
    try {
      redirectTo(await start());
    } catch (e) {
      const message = errorMessage(e, 'Could not start checkout. Please try again.');
      track('billing_checkout_redirect_failed', { error_message: message });
      openWithError(message);
      setPendingId(null);
    }
  };

  const onSubscribe = (priceId: string) => {
    track('billing_subscription_checkout_started', { price_id: priceId });
    void go(priceId, () => billingService.startSubscriptionCheckout(priceId));
  };

  const onBuy = (productId: string) => {
    track('billing_purchase_checkout_started', { product_id: productId });
    void go(productId, () => billingService.startPurchaseCheckout(productId));
  };

  const onManage = async () => {
    try {
      const url = await billingService.openBillingPortal();
      track('billing_portal_opened');
      redirectTo(url);
    } catch (e) {
      openWithError(errorMessage(e, 'Could not open the billing portal.'));
    }
  };

  const subscription = data?.subscription;
  const productNames = new Map((data?.products ?? []).map((p) => [p.id, p.name]));

  return (
    <Dialog open={isOpen} onOpenChange={(next) => (next ? null : close())}>
      <DialogContent className="max-w-[640px]">
        <DialogHeader>
          <DialogTitle className="font-sans text-base font-semibold tracking-tight">Billing</DialogTitle>
          <p className="mt-1 font-sans text-xs text-muted-foreground">Manage your plan and one-time purchases.</p>
        </DialogHeader>

        <div className="max-h-[65vh] space-y-6 overflow-y-auto px-6 pb-4">
          {error && <ErrorBanner message={error} />}
          {isLoading && !data && <div className="py-6 font-sans text-sm text-muted-foreground">Loading…</div>}

          {data && (
            <>
              <section className="space-y-3">
                <h3 className="font-sans text-sm font-semibold text-foreground">Subscription</h3>
                {subscription?.isActive ? (
                  <div className="flex items-center justify-between gap-3 rounded-xl border border-border bg-card p-4">
                    <div className="font-sans text-sm text-foreground">
                      Status: <span className="font-medium capitalize">{subscription.status}</span>
                      {subscription.currentPeriodEnd && (
                        <span className="text-muted-foreground">
                          {' '}· {subscription.cancelAtPeriodEnd ? 'ends' : 'renews'}{' '}
                          {new Date(subscription.currentPeriodEnd).toLocaleDateString()}
                        </span>
                      )}
                    </div>
                    <Button type="button" variant="outline" size="sm" onClick={onManage}>
                      Manage subscription
                    </Button>
                  </div>
                ) : (
                  <>
                    <p className="font-sans text-xs text-muted-foreground">You have no active subscription.</p>
                    {data.prices.length === 0 ? (
                      <p className="font-sans text-xs text-muted-foreground">No plans are available yet.</p>
                    ) : (
                      <div className="grid gap-3 sm:grid-cols-2">
                        {data.prices.map((price) => (
                          <ProductCard
                            key={price.id}
                            title={price.product?.name ?? 'Plan'}
                            description={price.product?.description}
                            priceLabel={recurringLabel(price.unitAmount, price.currency, price.recurring!.interval, price.recurring!.intervalCount)}
                            actionLabel={pendingId === price.id ? 'Redirecting…' : 'Subscribe'}
                            ariaLabel={`Subscribe to ${price.product?.name ?? 'plan'}`}
                            disabled={pendingId !== null}
                            onAction={() => onSubscribe(price.id)}
                          />
                        ))}
                      </div>
                    )}
                  </>
                )}
              </section>

              <section className="space-y-3">
                <h3 className="font-sans text-sm font-semibold text-foreground">One-time purchases</h3>
                <div className="grid gap-3 sm:grid-cols-2">
                  {data.products.map((product) => (
                    <ProductCard
                      key={product.id}
                      title={product.name}
                      description={product.description}
                      priceLabel={formatAmount(product.amountCents, product.currency)}
                      actionLabel={pendingId === product.id ? 'Redirecting…' : 'Buy'}
                      ariaLabel={`Buy ${product.name}`}
                      disabled={pendingId !== null}
                      onAction={() => onBuy(product.id)}
                    />
                  ))}
                </div>
                {data.purchases.length > 0 && (
                  <ul className="divide-y divide-border rounded-xl border border-border">
                    {data.purchases.slice(0, 10).map((purchase) => (
                      <li key={purchase.id} className="flex items-center justify-between px-4 py-2 font-sans text-xs">
                        <span className="text-foreground">{productNames.get(purchase.productId) ?? purchase.productId}</span>
                        <span className="text-muted-foreground">
                          {formatAmount(purchase.amountTotalCents ?? purchase.amountSubtotalCents, purchase.currency)} ·{' '}
                          {STATUS_LABEL[purchase.status] ?? purchase.status} ·{' '}
                          {new Date(purchase.createdAt).toLocaleDateString()}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            </>
          )}
        </div>

        <DialogFooter>
          <button type="button" onClick={onManage} className="font-sans text-xs text-muted-foreground underline-offset-2 hover:underline">
            Payments &amp; invoices →
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
