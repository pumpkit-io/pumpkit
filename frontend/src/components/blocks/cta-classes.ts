import { cn } from '@/lib/utils';

/** White with a thin shadow at rest, orange with white text on hover or focus in both themes; ArrowLabel's arrow follows the text color. */
export const CTA_CLASSES = cn(
  'group/cta border border-black/10 bg-white text-neutral-900 shadow-[0_1px_2px_rgb(0_0_0/0.14),0_3px_8px_rgb(0_0_0/0.08),inset_0_-1px_0_rgb(0_0_0/0.06)]',
  'transition-[color,background-color,border-color,box-shadow] duration-200',
  // The light theme's primary, fixed: dark mode's lighter primary has too little contrast with white text.
  'hover:border-[hsl(15.1_62.3%_43.7%)] hover:bg-[hsl(15.1_62.3%_43.7%)] hover:text-white',
  'focus-visible:bg-[hsl(15.1_62.3%_43.7%)] focus-visible:text-white',
);
