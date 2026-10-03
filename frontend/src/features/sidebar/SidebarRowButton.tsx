import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react';
import { cn } from '@/lib/utils';

interface SidebarRowButtonProps
  extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'children'> {
  icon: ReactNode;
  label: string;
  trailing?: ReactNode;
}

export const SidebarRowButton = forwardRef<HTMLButtonElement, SidebarRowButtonProps>(
  function SidebarRowButton(
    { icon, label, trailing, className, ...rest },
    ref,
  ) {
    return (
      <button
        {...rest}
        ref={ref}
        type="button"
        className={cn(
          'group mx-2 flex h-10 w-[calc(100%-1rem)] items-center gap-2.5 rounded-lg px-2.5',
          'font-sans text-sm text-foreground transition-colors',
          'hover:bg-[var(--hover)]',
          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-0',
          className,
        )}
      >
        <span className="flex h-5 w-5 shrink-0 items-center justify-center text-muted-foreground transition-colors group-hover:text-foreground">
          {icon}
        </span>
        <span className="truncate">{label}</span>
        {trailing && <span className="ml-auto inline-flex items-center">{trailing}</span>}
      </button>
    );
  },
);
