import { useEffect, type ReactNode } from 'react';
import { ErrorBanner } from '@/components/ErrorBanner';
import { SettingsCard } from '@/components/SettingsCard';
import { cn } from '@/lib/utils';
import type { AllowanceUsage, TopUpUsage, UsageCount } from '@/services/usageService';
import { AllowanceInfo, type AllowanceTopic } from './AllowanceInfo';
import { BuyTopUpButton } from './BuyTopUp';
import { SubscribeNowButton } from './SubscribeNow';
import { allowanceDay, isLow, resetsLine } from './usage';
import { useUsage } from './useUsage';
import { useOpenPortal } from './useOpenPortal';

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
  topic: AllowanceTopic;
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

/** What each Top-up has left, first to expire first; nothing while none has anything left. */
function TopUpsLeft({ topUps }: { topUps: TopUpUsage[] }) {
  if (topUps.length === 0) return null;
  return (
    <ul aria-label="Top-ups" className="space-y-1 font-sans text-sm text-foreground">
      {topUps.map((topUp) => (
        <li key={topUp.expiresAt.toISOString()}>
          Top-up: {topUp.generationsLeft} generations and {topUp.xPostsLeft} X posts left, until{' '}
          {allowanceDay(topUp.expiresAt, { withYear: true })}
        </li>
      ))}
    </ul>
  );
}

function UsageDetails({
  allowance,
  onSubscribed,
}: {
  allowance: AllowanceUsage;
  onSubscribed: () => void;
}) {
  const { openPortal, error } = useOpenPortal();
  const {
    trial,
    generations,
    xPosts,
    linkXPosts,
    resetsAt,
    resetsOnDay,
    wayOut,
    topUps,
    mayBuyTopUp,
  } = allowance;

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
        topic="xPosts"
      />
      <div className="space-y-0.5 font-sans text-xs text-muted-foreground">
        <p>
          {trial || resetsOnDay === null
            ? `Your trial ends on ${allowanceDay(resetsAt)}`
            : resetsLine(resetsOnDay)}
        </p>
        <p>Unused generations and X posts don&apos;t carry over.</p>
      </div>
      {wayOut === 'subscribe_now' && (
        <SubscribeNowButton className="h-10" onSubscribed={onSubscribed} />
      )}
      {(topUps.length > 0 || mayBuyTopUp) && (
        <div className="space-y-3">
          <TopUpsLeft topUps={topUps} />
          {mayBuyTopUp && <BuyTopUpButton className="h-9" />}
        </div>
      )}
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

// How long the webhook that adds a bought Top-up usually takes to land after Stripe's redirect.
const TOP_UP_SYNC_WAIT_MS = 4000;

/** Back from buying a Top-up, loads usage once more after a wait, in case the webhook was late. */
function useReloadAfterTopUp(topUpBought: boolean, reload: () => void) {
  useEffect(() => {
    if (!topUpBought) return;
    const timeout = window.setTimeout(reload, TOP_UP_SYNC_WAIT_MS);
    return () => window.clearTimeout(timeout);
  }, [topUpBought, reload]);
}

/**
 * What a Subscribed User has left of their Allowance this period, counted in what is left with a
 * bar under each count. Renders nothing where there is no Allowance.
 */
export function UsageCard({ topUpBought = false }: { topUpBought?: boolean }) {
  const { usage, failed, reload } = useUsage();
  useReloadAfterTopUp(topUpBought, reload);

  if (usage && !usage.allowance) return null;
  return (
    <SettingsCard title="Usage">
      {usage?.allowance ? (
        <UsageDetails allowance={usage.allowance} onSubscribed={reload} />
      ) : failed ? (
        <ErrorBanner message="Couldn't load your usage. Reload the page to try again." />
      ) : (
        <UsageSkeleton />
      )}
    </SettingsCard>
  );
}
