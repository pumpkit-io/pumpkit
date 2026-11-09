import { useCallback, useEffect, useRef, useState } from 'react';
import { storageKey } from '@/lib/storage';
import { errorMessage, errorStatus } from '@/services/apiErrors';
import { billingService, type PlanChange, type PlanChangeRequest } from '@/services/billingService';

function savedRequest(): PlanChangeRequest | null {
  try {
    const value: unknown = JSON.parse(sessionStorage.getItem(storageKey('plan-change')) ?? 'null');
    if (!value || typeof value !== 'object') return null;
    const request = value as PlanChangeRequest;
    return typeof request.operationId === 'string' && typeof request.revision === 'string'
      ? request
      : null;
  } catch {
    return null;
  }
}

export function usePlanChange(accountOperationId?: string | null) {
  const [request, setRequest] = useState(savedRequest);
  const [pendingId, setPendingId] = useState<string | null>(
    accountOperationId ?? request?.operationId ?? null,
  );
  const [answer, setAnswer] = useState<PlanChange | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const running = useRef(false);
  const clear = useCallback(() => {
    setRequest(null);
    setPendingId(null);
    try {
      sessionStorage.removeItem(storageKey('plan-change'));
    } catch {
      // The account still retains accepted operations when browser storage is unavailable.
    }
  }, []);

  const execute = useCallback(
    async (id: string, original: PlanChangeRequest | null, create: boolean) => {
      if (running.current) return null;
      running.current = true;
      setBusy(true);
      setError(null);
      if (create && original) {
        try {
          sessionStorage.setItem(storageKey('plan-change'), JSON.stringify(original));
        } catch {
          setError("Couldn't save this change for recovery. Allow browser storage and try again.");
          setBusy(false);
          running.current = false;
          return null;
        }
        setRequest(original);
      }
      setPendingId(id);
      let confirming = create;
      try {
        let result: PlanChange;
        if (create && original) result = await billingService.createPlanChange(original);
        else {
          try {
            result = await billingService.fetchPlanChange(id);
          } catch (cause) {
            if (errorStatus(cause) !== 404) throw cause;
            if (!original) {
              clear();
              return null;
            }
            confirming = true;
            result = await billingService.createPlanChange(original);
          }
        }
        setAnswer(result);
        if (result.status !== 'pending') clear();
        return result;
      } catch (cause) {
        if (confirming && [400, 409, 422].includes(errorStatus(cause) ?? 0)) {
          clear();
          setError(errorMessage(cause, 'Review the current plan and future payment date again.'));
        } else {
          setError(
            'Your billing frequency change is not confirmed yet. Check the change to retrieve its result safely.',
          );
        }
        return null;
      } finally {
        running.current = false;
        setBusy(false);
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
      void execute(id, original?.operationId === id ? original : null, false);
    }
  }, [accountOperationId, execute]);

  return {
    pending: Boolean(pendingId),
    busy,
    error,
    answer,
    submit: (next: PlanChangeRequest) => execute(next.operationId, next, true),
    check: () =>
      pendingId
        ? execute(pendingId, request?.operationId === pendingId ? request : null, false)
        : Promise.resolve(null),
    reset: () => {
      setAnswer(null);
      setError(null);
    },
  };
}
