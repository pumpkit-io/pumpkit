import { useState } from 'react';
import { track } from '@/lib/analytics';
import { redirectTo } from '@/lib/navigation';
import { errorMessage } from '@/services/apiErrors';
import { billingService } from '@/services/billingService';

/** Opens the billing portal, with the error to show when it couldn't. */
export function useOpenPortal(): { openPortal: () => Promise<void>; error: string | null } {
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

  return { openPortal, error };
}
