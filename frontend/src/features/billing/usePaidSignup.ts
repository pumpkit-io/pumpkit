import { useCallback, useEffect, useRef, useState } from 'react';
import { storageKey } from '@/lib/storage';
import { errorMessage, errorStatus } from '@/services/apiErrors';
import { billingService, type PaidSignup, type PaidSignupRequest } from '@/services/billingService';

function savedRequest(): PaidSignupRequest | null {
  try {
    const value: unknown = JSON.parse(sessionStorage.getItem(storageKey('paid-signup')) ?? 'null');
    if (!value || typeof value !== 'object') return null;
    const request = value as PaidSignupRequest;
    return typeof request.operationId === 'string' &&
      typeof request.revision === 'string' &&
      (request.termsVersion === null || typeof request.termsVersion === 'string') &&
      typeof request.acceptedTerms === 'boolean' &&
      typeof request.requestedImmediateStart === 'boolean' &&
      typeof request.approvedSpecificClauses === 'boolean' &&
      (request.language === 'en' || request.language === 'it')
      ? request
      : null;
  } catch {
    return null;
  }
}

export function usePaidSignup(accountOperationId?: string | null) {
  const [request, setRequest] = useState(savedRequest);
  const [answer, setAnswer] = useState<PaidSignup | null>(null);
  const [pendingId, setPendingId] = useState<string | null>(
    accountOperationId ?? request?.operationId ?? null,
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const running = useRef(false);
  const clear = useCallback(() => {
    setRequest(null);
    setPendingId(null);
    try {
      sessionStorage.removeItem(storageKey('paid-signup'));
    } catch {
      // Account recovery remains available when browser storage is unavailable.
    }
  }, []);

  const execute = useCallback(
    async (
      id: string,
      original: PaidSignupRequest | null,
      action: 'create' | 'check' | 'cancel',
    ) => {
      if (running.current) return null;
      running.current = true;
      setBusy(true);
      setError(null);
      if (original && action === 'create') {
        try {
          sessionStorage.setItem(storageKey('paid-signup'), JSON.stringify(original));
        } catch {
          setError("Couldn't save this signup for recovery. Allow browser storage and try again.");
          setBusy(false);
          running.current = false;
          return null;
        }
        setRequest(original);
      }
      setPendingId(id);
      let confirming = action === 'create';
      try {
        let result: PaidSignup;
        if (action === 'cancel') result = await billingService.cancelPaidSignup(id);
        else if (action === 'create' && original)
          result = await billingService.createPaidSignup(original);
        else {
          try {
            result = await billingService.fetchPaidSignup(id);
          } catch (cause) {
            if (errorStatus(cause) !== 404) throw cause;
            if (!original) {
              clear();
              return null;
            }
            confirming = true;
            result = await billingService.createPaidSignup(original);
          }
        }
        setAnswer(result);
        if (result.status !== 'pending') clear();
        return result;
      } catch (cause) {
        if (
          (confirming && [400, 409, 422].includes(errorStatus(cause) ?? 0)) ||
          (action === 'cancel' && errorStatus(cause) === 404)
        ) {
          clear();
          setError(
            errorMessage(cause, 'Review the current plan and payment date before trying again.'),
          );
        } else {
          setError(
            'Your subscription signup is not confirmed yet. Check signup to retrieve its result safely.',
          );
        }
        return null;
      } finally {
        setBusy(false);
        running.current = false;
      }
    },
    [clear],
  );

  const initialRequest = useRef(request);
  const recovered = useRef<string | null>(null);
  useEffect(() => {
    const original = initialRequest.current;
    initialRequest.current = null;
    const id = accountOperationId ?? original?.operationId;
    if (id && recovered.current !== id) {
      recovered.current = id;
      void execute(id, original?.operationId === id ? original : null, 'check');
    }
  }, [accountOperationId, execute]);

  return {
    pending: Boolean(pendingId),
    busy,
    error,
    answer,
    submit: (next: PaidSignupRequest) => execute(next.operationId, next, 'create'),
    check: () =>
      pendingId
        ? execute(pendingId, request?.operationId === pendingId ? request : null, 'check')
        : Promise.resolve(null),
    cancel: () => (pendingId ? execute(pendingId, null, 'cancel') : Promise.resolve(null)),
    reset: () => {
      setAnswer(null);
      setError(null);
    },
  };
}
