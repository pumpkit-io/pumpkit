import { useCallback, useEffect, useRef, useState } from 'react';
import { errorMessage, errorStatus } from '@/services/apiErrors';
import {
  billingService,
  type CouponRedemption,
  type CouponRedemptionRequest,
} from '@/services/billingService';
import { storageKey } from '@/lib/storage';

function savedRequest(): CouponRedemptionRequest | null {
  try {
    const value: unknown = JSON.parse(
      sessionStorage.getItem(storageKey('coupon-redemption')) ?? 'null',
    );
    if (!value || typeof value !== 'object') return null;
    const request = value as CouponRedemptionRequest;
    return typeof request.operationId === 'string' &&
      typeof request.revision === 'string' &&
      (request.termsVersion === null || typeof request.termsVersion === 'string') &&
      typeof request.acceptedTerms === 'boolean' &&
      typeof request.approvedSpecificClauses === 'boolean' &&
      (request.language === 'en' || request.language === 'it')
      ? request
      : null;
  } catch {
    return null;
  }
}

export function useCouponRedemption(onConflict: () => void) {
  const [pending, setPending] = useState(savedRequest);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [completed, setCompleted] = useState<CouponRedemption | null>(null);
  const running = useRef(false);
  const conflict = useRef(onConflict);
  conflict.current = onConflict;

  const submit = useCallback(async (request: CouponRedemptionRequest, recover = false) => {
    if (running.current) return;
    running.current = true;
    setBusy(true);
    setError(null);
    try {
      sessionStorage.setItem(storageKey('coupon-redemption'), JSON.stringify(request));
    } catch {
      setError("Couldn't save this redemption for recovery. Allow browser storage and try again.");
      setBusy(false);
      running.current = false;
      return;
    }
    setPending(request);
    let confirming = !recover;
    try {
      let answer: CouponRedemption | null = null;
      if (recover) {
        try {
          answer = await billingService.fetchCouponRedemption(request.operationId);
        } catch (cause) {
          if (errorStatus(cause) !== 404) throw cause;
        }
      }
      if (!answer) {
        confirming = true;
        answer = await billingService.redeemCoupon(request);
      }
      setCompleted(answer);
      setPending(null);
      sessionStorage.removeItem(storageKey('coupon-redemption'));
    } catch (cause) {
      const status = errorStatus(cause);
      if (confirming && status !== null && status >= 400 && status < 500) {
        setPending(null);
        sessionStorage.removeItem(storageKey('coupon-redemption'));
        conflict.current();
        setError(
          errorMessage(
            cause,
            'Check the code again and review the current offer before redeeming.',
          ),
        );
      } else {
        setError(
          'Your redemption is not confirmed yet. Check redemption to retrieve its result safely.',
        );
      }
    } finally {
      setBusy(false);
      running.current = false;
    }
  }, []);

  const initial = useRef(pending);
  useEffect(() => {
    if (initial.current) void submit(initial.current, true);
  }, [submit]);

  return { pending, busy, error, completed, submit, clearError: () => setError(null) };
}
