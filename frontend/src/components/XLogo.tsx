import { cn } from '@/lib/utils';

interface XLogoProps {
  className?: string;
  label?: string;
  /** Hides the logo from screen readers, for text that already names X. */
  decorative?: boolean;
}

/** The X mark, in its text's colour and sized to it, so it is black or white with the theme. */
export function XLogo({ className, label = 'X', decorative = false }: XLogoProps) {
  return (
    <svg
      viewBox="0 0 1200 1227"
      fill="currentColor"
      className={cn('inline-block h-[0.85em] w-[0.83em] shrink-0 align-[-0.05em]', className)}
      {...(decorative ? { 'aria-hidden': true } : { role: 'img', 'aria-label': label })}
      focusable="false"
    >
      <path d="M714.163 519.284 1160.89 0h-105.86L667.137 450.887 357.328 0H0l468.492 681.821L0 1226.37h105.866l409.625-476.152 327.181 476.152H1200L714.137 519.284h.026ZM569.165 687.828l-47.468-67.894L144.011 79.694h162.604l304.797 435.991 47.468 67.894 396.2 566.721H892.476L569.165 687.854v-.026Z" />
    </svg>
  );
}
