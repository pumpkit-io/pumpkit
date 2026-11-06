import * as React from 'react';
import { Slot } from '@radix-ui/react-slot';
import { type VariantProps, cva } from 'class-variance-authority';
import { cn } from '../../lib/utils';

const RAISED =
  'shadow-[inset_0_1px_0_rgb(255_255_255/0.16),inset_0_-1px_2px_rgb(0_0_0/0.24),0_1px_1px_rgb(0_0_0/0.06),0_0_0_1px_rgb(0_0_0/0.16),0_8px_16px_-8px_rgb(0_0_0/0.5)] text-white transition-[transform,background-color,box-shadow] active:scale-[0.98] motion-reduce:active:scale-100 disabled:opacity-60';

const buttonVariants = cva(
  'inline-flex items-center justify-center whitespace-nowrap rounded-lg text-sm font-medium ring-offset-background transition-[color,background-color,border-color,filter] motion-reduce:transition-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60 focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50',
  {
    variants: {
      variant: {
        default:
          'bg-primary bg-primary-gradient text-primary-foreground shadow-[inset_0_1px_0_rgb(255_255_255/0.16),0_0_0_1px_hsl(var(--primary)),0_1px_2px_rgb(0_0_0/0.12)] hover:brightness-95 dark:hover:brightness-105 disabled:bg-muted disabled:bg-none disabled:text-muted-foreground disabled:opacity-100 disabled:shadow-none',
        // Lifted off the page, darkening on hover and pressing in on click.
        // The hover tint is an inset shadow, which paints over the gradient but under the label.
        raised: `${RAISED} bg-primary bg-primary-gradient hover:shadow-[inset_0_1px_0_rgb(255_255_255/0.16),inset_0_-1px_2px_rgb(0_0_0/0.24),0_1px_1px_rgb(0_0_0/0.06),0_0_0_1px_rgb(0_0_0/0.16),0_8px_16px_-8px_rgb(0_0_0/0.5),inset_0_0_0_999px_rgb(0_0_0/0.1)]`,
        pumpkin:
          'bg-[#D96B45] text-[#20201E] shadow-[inset_0_1px_0_rgb(255_255_255/0.16),0_0_0_1px_#D96B45,0_1px_2px_rgb(0_0_0/0.12)] hover:shadow-panel disabled:bg-muted disabled:text-muted-foreground disabled:opacity-100 disabled:shadow-none',
        raisedPumpkin: `${RAISED} bg-[#D96B45] text-[#20201E] hover:shadow-panel`,
        raisedNeutral: `${RAISED} bg-[var(--raised-neutral)] hover:bg-[var(--raised-neutral-hover)]`,
        // The primary fill without the gradient, for pages that keep gradients off.
        solid:
          'bg-primary text-primary-foreground hover:bg-primary/90 disabled:bg-muted disabled:text-muted-foreground disabled:opacity-100',
        destructive: 'bg-destructive text-destructive-foreground hover:bg-destructive/90',
        outline:
          'border border-border bg-card shadow-raised hover:bg-accent hover:text-accent-foreground',
        secondary: 'bg-secondary text-secondary-foreground hover:bg-secondary/80',
        ghost: 'hover:bg-[var(--hover)] hover:text-foreground',
        link: 'text-primary underline-offset-4 hover:underline',
      },
      size: {
        default: 'h-10 px-4 py-2',
        sm: 'h-9 rounded-md px-3',
        lg: 'h-11 rounded-md px-8',
        icon: 'h-10 w-10',
      },
    },
    defaultVariants: {
      variant: 'default',
      size: 'default',
    },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : 'button';
    return (
      <Comp className={cn(buttonVariants({ variant, size, className }))} ref={ref} {...props} />
    );
  },
);
Button.displayName = 'Button';

export { Button, buttonVariants };
