import { useState, type ReactNode } from 'react';
import { ErrorBanner } from '@/components/ErrorBanner';
import { SettingsCard } from '@/components/SettingsCard';
import { track } from '@/lib/analytics';
import { redirectTo } from '@/lib/navigation';
import { cn } from '@/lib/utils';
import { errorMessage } from '@/services/apiErrors';
import { billingService } from '@/services/billingService';
import type { AllowanceUsage, UsageCount } from '@/services/usageService';
import { AllowanceInfo, type AllowanceInfoTopic } from './AllowanceInfo';
import { allowanceDay, isLow } from './usage';
import { useUsage } from './useUsage';

/** The count left, then what it counts: "382 generations left", or out of the Trial's limit. */
function leftLine(count: UsageCount, noun: string, trial: boolean): ReactNode {
  const left = <span className="text-lg font-semibold leading-tight">{count.left}</span>;
  return trial ? (
    <>
      {left} of {count.limit} {noun} left in your trial
    </>
  ) : (
    <>
      {left} {noun} left
    </>
  );
}

/** The hairline bar of what is left: primary, warning under a tenth left, destructive at none. */
function LeftBar({ count, label }: { count: UsageCount; label: string }) {
  const limit = count.limit ?? 0;
  const left = count.left ?? 0;
  const share = limit > 0 ? Math.min(1, left / limit) : 0;
  return (
    <div
      role="meter"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={limit}
      aria-valuenow={left}
      className="h-1 w-full overflow-hidden rounded-full bg-muted"
    >
      <div
        className={cn(
          'h-full rounded-full',
          left === 0 ? 'bg-destructive' : isLow(count) ? 'bg-warning' : 'bg-primary',
        )}
        style={{ width: `${share * 100}%` }}
      />
    </div>
  );
}

/** One count's line, info button and bar; nothing for a count with no cap. */
function CountLeft({
  count,
  line,
  label,
  topic,
}: {
  count: UsageCount;
  line: ReactNode;
  label: string;
  topic: AllowanceInfoTopic;
}) {
  if (count.limit === null) return null;
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-3">
        <p className="font-sans text-sm text-foreground">{line}</p>
        <AllowanceInfo topic={topic} />
      </div>
      <LeftBar count={count} label={label} />
    </div>
  );
}

function UsageDetails({ allowance }: { allowance: AllowanceUsage }) {
  const [error, setError] = useState<string | null>(null);
  const { trial, generations, xPosts, linkXPosts, resetsAt, wayOut } = allowance;

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

  const withLinks = linkXPosts.limit === null ? null : `, ${linkXPosts.left} of them with a link`;

  return (
    <div className="space-y-4">
      {error && <ErrorBanner message={error} />}
      <CountLeft
        count={generations}
        line={leftLine(generations, 'generations', trial)}
        label="Generations left"
        topic="generations"
      />
      <CountLeft
        count={xPosts}
        line={
          <>
            {leftLine(xPosts, 'X posts', trial)}
            {withLinks}
          </>
        }
        label="X posts left"
        topic="x_posts"
      />
      <div className="space-y-0.5 font-sans text-xs text-muted-foreground">
        <p>
          {trial
            ? `Your trial ends on ${allowanceDay(resetsAt)}`
            : `Resets on ${allowanceDay(resetsAt)}`}
        </p>
        <p>Unused generations and X posts don&apos;t carry over.</p>
      </div>
      {/* The Top-up block and Buy top-up (#233), and Subscribe now during a Trial (#235), go here. */}
      {wayOut === 'update_payment' && (
        <button
          type="button"
          onClick={() => void openPortal()}
          className="rounded-sm font-sans text-sm text-foreground underline underline-offset-4 hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          Update your payment method to buy a top-up
        </button>
      )}
    </div>
  );
}

/** The card's shape at its final height while usage loads. */
function UsageSkeleton() {
  const bone = 'rounded bg-muted motion-safe:animate-pulse';
  return (
    <div role="status" className="space-y-4">
      <span className="sr-only">Loading your usage…</span>
      {[0, 1].map((row) => (
        <div key={row} aria-hidden="true" className="space-y-2">
          <div className={cn(bone, 'h-6', row === 0 ? 'w-48' : 'w-64')} />
          <div className={cn(bone, 'h-1 w-full rounded-full')} />
        </div>
      ))}
      <div aria-hidden="true" className="space-y-1.5">
        <div className={cn(bone, 'h-3 w-40')} />
        <div className={cn(bone, 'h-3 w-72 max-w-full')} />
      </div>
    </div>
  );
}

/**
 * What a Subscribed User has left of their Allowance this period, counted in what is left with a
 * bar under each count. Renders nothing where there is no Allowance.
 */
export function UsageCard() {
  const { usage, failed } = useUsage();

  if (usage && !usage.allowance) return null;
  return (
    <SettingsCard title="Usage">
      {usage?.allowance ? (
        <UsageDetails allowance={usage.allowance} />
      ) : failed ? (
        <ErrorBanner message="Couldn't load your usage. Reload the page to try again." />
      ) : (
        <UsageSkeleton />
      )}
    </SettingsCard>
  );
}
