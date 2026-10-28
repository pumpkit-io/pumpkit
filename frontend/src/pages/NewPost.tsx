import { useEffect, useRef } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useBilling } from '@/features/billing/useBilling';
import { PersonaChip } from '@/features/inspirationAuthors/PersonaChip';
import { PostWriter } from '@/features/posts/PostWriter';
import { Topbar } from '@/features/topbar/Topbar';
import { track } from '@/lib/analytics';
import { fireSuccessConfetti } from '@/lib/confetti';

interface NewPostLocationState {
  checkoutStatus?: 'success' | 'cancelled';
  openBilling?: boolean;
}

/** Opens the billing dialog when arriving from Stripe or /billing. */
function useBillingReturn() {
  const location = useLocation();
  const navigate = useNavigate();
  const billing = useBilling();
  const consumedRef = useRef(false);

  useEffect(() => {
    if (consumedRef.current) return;
    const state = (location.state ?? {}) as NewPostLocationState;
    if (!state.checkoutStatus && !state.openBilling) return;
    consumedRef.current = true;
    navigate('.', { replace: true, state: null });

    if (state.checkoutStatus === 'success') {
      track('billing_checkout_succeeded');
      fireSuccessConfetti(null);
      billing.open('checkout_success');
    } else if (state.checkoutStatus === 'cancelled') {
      track('billing_checkout_cancelled');
      billing.openWithError(
        'Checkout was cancelled. You have not been charged.',
        'checkout_cancelled',
      );
    } else {
      billing.open('billing_route');
    }
  }, [location.state, navigate, billing]);
}

/** The Brief form; writing a Post opens the Post's page. */
export function NewPost() {
  useBillingReturn();

  return (
    <>
      <Topbar title="New post" actions={<PersonaChip />} />
      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-2xl px-4 py-8 sm:px-6">
          <PostWriter />
        </div>
      </div>
    </>
  );
}
