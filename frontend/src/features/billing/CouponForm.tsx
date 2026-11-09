import { useEffect, useId, useRef, useState, type FormEvent } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { errorMessage } from '@/services/apiErrors';
import { billingService, type CouponPreview } from '@/services/billingService';
import { count } from './counts';
import { CouponAcceptanceFields, type CouponAcceptance } from './CouponAcceptanceFields';
import type { LegalLanguage } from '@/features/legal/documents';
import { useCouponRedemption } from './useCouponRedemption';
import { useBilling } from './useBilling';
import { useOnboarding } from '@/features/onboarding/useOnboarding';

function exactDate(value: string): string {
  return `${new Date(value).toLocaleDateString(undefined, {
    dateStyle: 'medium',
    timeZone: 'UTC',
  })} UTC`;
}

export function CouponForm({
  inSettings = false,
  onRedeemed,
  recoveryOnly = false,
  operationId,
  onPendingChange,
}: {
  inSettings?: boolean;
  onRedeemed?: () => void;
  recoveryOnly?: boolean;
  operationId?: string | null;
  onPendingChange?: (pending: boolean) => void;
}) {
  const afterRedemption = useRef(onRedeemed);
  afterRedemption.current = onRedeemed;
  const id = useId();
  const input = useRef<HTMLInputElement>(null);
  const result = useRef<HTMLDivElement>(null);
  const [expanded, setExpanded] = useState(false);
  const [code, setCode] = useState('');
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<CouponPreview | null>(null);
  const [language, setLanguage] = useState<LegalLanguage>('en');
  const [acceptance, setAcceptance] = useState<CouponAcceptance>({
    acceptedTerms: false,
    approvedSpecificClauses: false,
  });
  const { load } = useBilling();
  const { refresh } = useOnboarding();
  const redemption = useCouponRedemption(() => {
    setPreview(null);
    setAcceptance({ acceptedTerms: false, approvedSpecificClauses: false });
  }, operationId);
  const success = useRef<HTMLParagraphElement>(null);
  const redemptionError = useRef<HTMLParagraphElement>(null);
  const [continuing, setContinuing] = useState(false);
  const [continueError, setContinueError] = useState(false);
  const blocked =
    checking || redemption.busy || Boolean(redemption.pending) || Boolean(redemption.completed);

  const wasPending = useRef(redemption.pending);
  useEffect(() => {
    onPendingChange?.(redemption.pending);
    if (wasPending.current && !redemption.pending && !redemption.completed) void load();
    wasPending.current = redemption.pending;
  }, [onPendingChange, redemption.pending, redemption.completed, load]);

  useEffect(() => {
    if (redemption.completed) {
      success.current?.focus();
      afterRedemption.current?.();
    }
  }, [redemption.completed]);

  useEffect(() => {
    if (redemption.error) redemptionError.current?.focus();
  }, [redemption.error]);

  async function continueToApp() {
    setContinuing(true);
    const next = await refresh();
    const failed = next === undefined || next === 'paywall';
    setContinueError(failed);
    if (!failed) await load();
    setContinuing(false);
  }

  useEffect(() => {
    if (expanded) input.current?.focus();
  }, [expanded]);
  useEffect(() => {
    if (error && !checking) input.current?.focus();
  }, [error, checking]);
  useEffect(() => {
    if (preview) result.current?.focus();
  }, [preview]);

  async function check(event: FormEvent) {
    event.preventDefault();
    if (!code.trim() || blocked) return;
    setChecking(true);
    setError(null);
    redemption.clearError();
    setPreview(null);
    setAcceptance({ acceptedTerms: false, approvedSpecificClauses: false });
    try {
      setPreview(await billingService.previewCoupon(code.trim()));
    } catch (cause) {
      setError(errorMessage(cause, "Couldn't check this coupon. Try again."));
    } finally {
      setChecking(false);
    }
  }

  return (
    <section className="ph-no-capture max-w-[560px] break-words text-left">
      {!recoveryOnly && (
        <Button
          type="button"
          variant="link"
          className="h-auto min-h-11 max-w-full whitespace-normal px-0 text-left focus-visible:ring-ring"
          aria-expanded={expanded}
          aria-controls={`${id}-form`}
          disabled={blocked}
          onClick={() => setExpanded(!expanded)}
        >
          {inSettings ? 'Redeem coupon' : 'Have a coupon?'}
        </Button>
      )}
      {redemption.completed && (
        <div className="space-y-3 text-sm text-foreground">
          <p
            ref={success}
            role="status"
            tabIndex={-1}
            className="font-semibold focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring"
          >
            Coupon redeemed
          </p>
          <p>
            {count(redemption.completed.months, 'free month', 'free months')}:{' '}
            {exactDate(redemption.completed.startsAt)} to {exactDate(redemption.completed.endsAt)}.
          </p>
          <p>
            {redemption.completed.nextPaymentAt
              ? `Next payment: ${exactDate(redemption.completed.nextPaymentAt)}`
              : 'No automatic payment'}
          </p>
          {continueError && (
            <p role="alert">Couldn’t refresh your access. Continue again to check.</p>
          )}
          {inSettings && !recoveryOnly ? (
            <Button
              type="button"
              className="h-auto min-h-11 max-w-full whitespace-normal"
              onClick={() => {
                redemption.resetCompleted();
                setCode('');
                setPreview(null);
                setAcceptance({ acceptedTerms: false, approvedSpecificClauses: false });
                setExpanded(true);
                requestAnimationFrame(() => input.current?.focus());
              }}
            >
              Redeem another coupon
            </Button>
          ) : (
            <Button type="button" disabled={continuing} onClick={() => void continueToApp()}>
              {continuing ? 'Continuing…' : 'Continue'}
            </Button>
          )}
        </div>
      )}
      {redemption.error && (
        <p
          ref={redemptionError}
          tabIndex={-1}
          role="alert"
          className="text-sm text-destructive focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring"
        >
          {redemption.error}
        </p>
      )}
      {(redemption.pending || redemption.busy) && !redemption.completed && (
        <div className="space-y-3">
          <p role="status" className="text-sm text-muted-foreground">
            Confirming redemption…
          </p>
          <p className="text-sm text-foreground">
            Your redemption is not confirmed yet. Check its result before trying another code.
          </p>
          <Button type="button" disabled={redemption.busy} onClick={redemption.check}>
            Check redemption
          </Button>
        </div>
      )}
      {expanded && !recoveryOnly && !redemption.completed && (
        <form id={`${id}-form`} onSubmit={(event) => void check(event)} className="space-y-4">
          <div className="space-y-2">
            <label htmlFor={`${id}-code`} className="text-sm font-medium text-foreground">
              Coupon code
            </label>
            <div className="flex flex-col gap-2 sm:flex-row sm:items-start">
              <Input
                ref={input}
                id={`${id}-code`}
                value={code}
                maxLength={256}
                autoComplete="off"
                autoCapitalize="none"
                spellCheck={false}
                disabled={blocked}
                aria-invalid={Boolean(error)}
                aria-describedby={error ? `${id}-error` : undefined}
                className="min-h-11 min-w-0 focus-visible:ring-2 focus-visible:ring-ring"
                onChange={(event) => {
                  setCode(event.target.value);
                  setError(null);
                  redemption.clearError();
                  setPreview(null);
                }}
              />
              <Button
                type="submit"
                variant="solid"
                className="min-h-11 shrink-0 focus-visible:ring-ring hover:bg-primary hover:brightness-95"
                disabled={!code.trim() || blocked}
              >
                {checking ? 'Checking…' : 'Check code'}
              </Button>
            </div>
          </div>
          {checking && (
            <p role="status" className="text-sm text-muted-foreground">
              Checking coupon…
            </p>
          )}
          {error && (
            <p id={`${id}-error`} role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}
          {preview && (
            <div
              ref={result}
              tabIndex={-1}
              role="status"
              aria-label="Coupon preview"
              aria-live="polite"
              className="space-y-3 rounded-lg bg-card p-4 text-sm text-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring"
            >
              <p className="font-semibold">{count(preview.months, 'free month', 'free months')}</p>
              <dl className="space-y-2">
                <div>
                  <dt className="text-muted-foreground">
                    {inSettings ? 'Starts' : 'Starts when you redeem'}
                  </dt>
                  <dd>
                    <time dateTime={preview.startsAt}>{exactDate(preview.startsAt)}</time>
                  </dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Ends</dt>
                  <dd>
                    <time dateTime={preview.endsAt}>{exactDate(preview.endsAt)}</time>
                  </dd>
                </div>
              </dl>
              <p>
                Each month:{' '}
                {preview.allowance.generations === null
                  ? 'unlimited generations'
                  : count(preview.allowance.generations, 'generation', 'generations')}
                ,{' '}
                {preview.allowance.xPosts === null
                  ? 'unlimited X posts'
                  : count(preview.allowance.xPosts, 'X post', 'X posts')}
                {preview.allowance.linkXPosts === null
                  ? ''
                  : `, including ${count(preview.allowance.linkXPosts, 'link post', 'link posts')}`}
                .
              </p>
              <p className="font-medium">
                {preview.nextPaymentAt
                  ? `Next payment: ${exactDate(preview.nextPaymentAt)}`
                  : language === 'it'
                    ? 'Nessun pagamento automatico'
                    : 'No automatic payment'}
              </p>
              <p lang={language}>
                {preview.nextPaymentAt
                  ? language === 'it'
                    ? 'Il tempo già pagato e l’utilizzo restano invariati. Il prossimo pagamento dell’abbonamento è posticipato fino alla fine dell’accesso gratuito.'
                    : 'Your remaining paid time and usage stay intact. Your next subscription payment moves to the end of free access.'
                  : language === 'it'
                    ? `L’accesso gratuito termina il ${exactDate(preview.endsAt)}. Non crea un abbonamento né un obbligo di pagamento.`
                    : `Free access ends on ${exactDate(preview.endsAt)}. This creates no subscription or obligation to pay.`}
              </p>
              {preview.termsVersion && (
                <>
                  <label className="block text-xs">
                    Terms language
                    <select
                      value={language}
                      disabled={blocked}
                      className="ml-2 min-h-11 rounded border border-input bg-card px-2 text-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring"
                      onChange={(event) => {
                        setLanguage(event.target.value as LegalLanguage);
                        setAcceptance({ acceptedTerms: false, approvedSpecificClauses: false });
                      }}
                    >
                      <option value="en">English</option>
                      <option value="it">Italiano</option>
                    </select>
                  </label>
                  <CouponAcceptanceFields
                    language={language}
                    value={acceptance}
                    onChange={setAcceptance}
                    disabled={blocked}
                  />
                </>
              )}
              <Button
                type="button"
                className="h-auto min-h-11 max-w-full whitespace-normal focus-visible:ring-ring"
                disabled={
                  blocked ||
                  Boolean(
                    preview.termsVersion &&
                    (!acceptance.acceptedTerms || !acceptance.approvedSpecificClauses),
                  )
                }
                onClick={() =>
                  void redemption.submit({
                    operationId: crypto.randomUUID(),
                    revision: preview.revision,
                    termsVersion: preview.termsVersion,
                    ...acceptance,
                    language,
                  })
                }
              >
                Redeem coupon
              </Button>
            </div>
          )}
        </form>
      )}
    </section>
  );
}
