import { cn } from '@/lib/utils';

/** White with a thin shadow at rest, orange on hover or focus; ArrowLabel's arrow follows the text color. */
export const CTA_CLASSES = cn(
  'group/cta border border-black/10 bg-white text-neutral-900 shadow-[0_1px_2px_rgb(0_0_0/0.14),0_3px_8px_rgb(0_0_0/0.08),inset_0_-1px_0_rgb(0_0_0/0.06)]',
  'transition-[color,background-color,border-color,box-shadow] duration-200',
  'hover:border-primary hover:bg-primary hover:text-primary-foreground',
  'focus-visible:bg-primary focus-visible:text-primary-foreground',
);
