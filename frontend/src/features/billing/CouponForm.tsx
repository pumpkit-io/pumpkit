import { useEffect, useId, useRef, useState, type FormEvent } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { errorMessage } from '@/services/apiErrors';
import { billingService, type CouponPreview } from '@/services/billingService';
import { count } from './counts';

function exactDate(value: string): string {
  return `${new Date(value).toLocaleString(undefined, {
    dateStyle: 'medium',
    timeStyle: 'medium',
    timeZone: 'UTC',
  })} UTC`;
}

export function CouponForm() {
  const id = useId();
  const input = useRef<HTMLInputElement>(null);
  const result = useRef<HTMLDivElement>(null);
  const [expanded, setExpanded] = useState(false);
  const [code, setCode] = useState('');
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<CouponPreview | null>(null);

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
    if (!code.trim() || checking) return;
    setChecking(true);
    setError(null);
    setPreview(null);
    try {
      setPreview(await billingService.previewCoupon(code.trim()));
    } catch (cause) {
      setError(errorMessage(cause, "Couldn't check this coupon. Try again."));
    } finally {
      setChecking(false);
    }
  }

  return (
    <section className="ph-no-capture max-w-[560px] text-left">
      <Button
        type="button"
        variant="link"
        className="min-h-11 px-0 focus-visible:ring-ring"
        aria-expanded={expanded}
        aria-controls={`${id}-form`}
        disabled={checking}
        onClick={() => setExpanded(!expanded)}
      >
        Have a coupon?
      </Button>
      {expanded && (
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
                disabled={checking}
                aria-invalid={Boolean(error)}
                aria-describedby={error ? `${id}-error` : undefined}
                className="min-h-11 min-w-0 focus-visible:ring-2 focus-visible:ring-ring"
                onChange={(event) => {
                  setCode(event.target.value);
                  setError(null);
                  setPreview(null);
                }}
              />
              <Button
                type="submit"
                variant="solid"
                className="min-h-11 shrink-0 focus-visible:ring-ring hover:bg-primary hover:brightness-95"
                disabled={!code.trim() || checking}
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
                  <dt className="text-muted-foreground">Starts</dt>
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
                  : 'No automatic payment'}
              </p>
              <p>
                Free access ends on {exactDate(preview.endsAt)}. This creates no subscription or
                obligation to pay.
              </p>
            </div>
          )}
        </form>
      )}
    </section>
  );
}
