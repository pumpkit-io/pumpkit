import { useContext } from 'react';
import { BillingContext } from './BillingProvider';

export function useBilling() {
  const ctx = useContext(BillingContext);
  if (!ctx) {
    throw new Error('useBilling must be used within a BillingProvider');
  }
  return ctx;
}
