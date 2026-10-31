import { Info } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';

/** What counts against each Allowance count a User can ask about. */
const WHAT_COUNTS = {
  generations: {
    label: 'About generations',
    text: 'Every prompt to generate or refine a post counts as one generation.',
  },
  xPosts: {
    label: 'About X posts',
    text: 'Scheduled posts and posts you post now both count. For threads, each post in the thread counts.',
  },
} as const;

export type AllowanceTopic = keyof typeof WHAT_COUNTS;

/** An info button that opens what counts as one generation or one X post. */
export function AllowanceInfo({ topic, className }: { topic: AllowanceTopic; className?: string }) {
  const { label, text } = WHAT_COUNTS[topic];
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label={label}
          className={cn(
            'inline-flex size-5 shrink-0 items-center justify-center rounded-full align-middle text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring motion-reduce:transition-none',
            className,
          )}
        >
          <Info aria-hidden className="size-3.5" />
        </button>
      </PopoverTrigger>
      <PopoverContent side="top" aria-label={label} className="w-64">
        <p className="font-sans text-sm leading-6 text-foreground">{text}</p>
      </PopoverContent>
    </Popover>
  );
}
