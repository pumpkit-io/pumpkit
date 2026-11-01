import { useSyncExternalStore } from 'react';
import { cn } from '@/lib/utils';

// Temporary: lets the maintainer compare resting styles for the landing CTAs. Delete once one is chosen.
export const CTA_STYLES = [
  { id: 'flat', label: 'Flat white' },
  { id: 'shadow', label: 'Thin shadow' },
  { id: 'edge', label: 'Orange edge' },
  { id: 'edge-shadow', label: 'Edge + shadow' },
] as const;

export type CtaStyleId = (typeof CTA_STYLES)[number]['id'];

const listeners = new Set<() => void>();
let current: CtaStyleId = 'shadow';

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useCtaStyle(): CtaStyleId {
  return useSyncExternalStore(subscribe, () => current);
}

const RESTING: Record<CtaStyleId, string> = {
  flat: 'border-transparent',
  shadow:
    'border-black/10 shadow-[0_1px_2px_rgb(0_0_0/0.14),0_3px_8px_rgb(0_0_0/0.08),inset_0_-1px_0_rgb(0_0_0/0.06)]',
  edge: 'border-primary shadow-none',
  'edge-shadow':
    'border-primary shadow-[0_1px_2px_rgb(0_0_0/0.14),0_3px_8px_rgb(0_0_0/0.08),inset_0_-1px_0_rgb(0_0_0/0.06)]',
};

/** White at rest and orange on hover or focus; the arrow in ArrowLabel follows the text color. */
export function ctaClasses(style: CtaStyleId): string {
  return cn(
    'group/cta border bg-white text-neutral-900 transition-[color,background-color,border-color,box-shadow] duration-200 hover:border-primary hover:bg-primary hover:text-primary-foreground focus-visible:bg-primary focus-visible:text-primary-foreground',
    RESTING[style],
  );
}

export function CtaStyleSwitcher() {
  const style = useCtaStyle();
  return (
    <div
      role="group"
      aria-label="Button style (temporary)"
      className="fixed bottom-4 right-4 z-50 flex flex-col gap-1 rounded-xl border bg-background p-2 text-sm shadow-lg"
    >
      <span className="px-2 pb-1 text-xs text-muted-foreground">Button style (temporary)</span>
      {CTA_STYLES.map((option) => (
        <button
          key={option.id}
          type="button"
          aria-pressed={style === option.id}
          onClick={() => {
            current = option.id;
            listeners.forEach((l) => l());
          }}
          className={cn(
            'rounded-md px-2 py-1 text-left hover:bg-accent',
            style === option.id && 'bg-accent font-medium',
          )}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}
