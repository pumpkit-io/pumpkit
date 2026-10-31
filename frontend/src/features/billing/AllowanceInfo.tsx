import { Info } from 'lucide-react';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';

/** What an info button explains: what counts against that part of the Allowance. */
export type AllowanceInfoTopic = 'generations' | 'x_posts';

const INFO: Record<AllowanceInfoTopic, { label: string; text: string }> = {
  generations: {
    label: 'What counts as a generation',
    text: 'Every prompt to generate or refine a post counts as one generation.',
  },
  x_posts: {
    label: 'What counts as an X post',
    text: 'Scheduled posts and posts you post now both count. For threads, each post in the thread counts.',
  },
};

/** An info button beside an Allowance line, opening what counts against it. */
export function AllowanceInfo({ topic }: { topic: AllowanceInfoTopic }) {
  const { label, text } = INFO[topic];
  return (
    <Popover>
      <PopoverTrigger
        aria-label={label}
        className="inline-flex size-6 shrink-0 items-center justify-center rounded-full text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <Info className="size-4" aria-hidden="true" />
      </PopoverTrigger>
      <PopoverContent align="end" className="w-64 font-sans text-sm text-foreground">
        {text}
      </PopoverContent>
    </Popover>
  );
}
