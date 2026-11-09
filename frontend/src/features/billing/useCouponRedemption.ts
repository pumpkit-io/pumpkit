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

export function useCouponRedemption(onConflict: () => void, operationId?: string | null) {
  const [request, setRequest] = useState(savedRequest);
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [completed, setCompleted] = useState<CouponRedemption | null>(null);
  const running = useRef(false);
  const conflict = useRef(onConflict);
  conflict.current = onConflict;

  const execute = useCallback(
    async (original: CouponRedemptionRequest | null, id: string, recover: boolean) => {
      if (running.current) return;
      running.current = true;
      setBusy(true);
      setError(null);
      if (original) {
        try {
          sessionStorage.setItem(storageKey('coupon-redemption'), JSON.stringify(original));
        } catch {
          setError(
            "Couldn't save this redemption for recovery. Allow browser storage and try again.",
          );
          setBusy(false);
          running.current = false;
          return;
        }
        setRequest(original);
      }
      setPendingId(id);
      let confirming = !recover;
      const clearPending = () => {
        setRequest(null);
        setPendingId(null);
        try {
          sessionStorage.removeItem(storageKey('coupon-redemption'));
        } catch {
          // Recovery from the account also works when browser storage is unavailable.
        }
      };
      try {
        let answer: CouponRedemption | null = null;
        if (recover) {
          try {
            answer = await billingService.fetchCouponRedemption(id);
          } catch (cause) {
            if (!original || errorStatus(cause) !== 404) throw cause;
          }
        }
        if (!answer && original) {
          confirming = true;
          answer = await billingService.redeemCoupon(original);
        }
        if (!answer || answer.status === 'pending') return;
        if (answer.status === 'refused') {
          conflict.current();
          setError(
            answer.detail ?? 'This redemption could not be completed. Check the code again.',
          );
        } else {
          setCompleted(answer);
        }
        clearPending();
      } catch (cause) {
        const status = errorStatus(cause);
        if (confirming && status !== null && [400, 409, 422].includes(status)) {
          clearPending();
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
    },
    [],
  );

  const initial = useRef(request);
  const recovered = useRef<string | null>(null);
  useEffect(() => {
    const original = initial.current;
    initial.current = null;
    const id = original?.operationId ?? operationId;
    if (id && recovered.current !== id) {
      recovered.current = id;
      void execute(original, id, true);
    }
  }, [execute, operationId]);

  return {
    pending: Boolean(request || pendingId),
    busy,
    error,
    completed,
    submit: (next: CouponRedemptionRequest) => execute(next, next.operationId, false),
    check: () => {
      const id = request?.operationId ?? pendingId;
      if (id) void execute(request, id, true);
    },
    clearError: () => setError(null),
    resetCompleted: () => setCompleted(null),
  };
}
