// CSS transitions, not framer-motion: its hardware-accelerated opacity fade shows the old value for a frame when it ends.
export const FADE = 'transition-opacity duration-150 ease-out motion-reduce:transition-none';
// Padding slides with the aside's 200ms width so the logo and toggle never jump.
export const SLIDE_AND_FADE =
  '[transition:opacity_150ms_ease-out,padding_200ms] motion-reduce:[transition:none]';
