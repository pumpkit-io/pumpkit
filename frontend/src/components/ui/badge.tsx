import * as React from 'react';
import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from '@/lib/utils';

const badgeVariants = cva(
  'inline-flex items-center rounded-full border px-2 py-0.5 font-mono text-[10px] uppercase tracking-wide transition-colors',
  {
    variants: {
      variant: {
        default: 'border-border bg-transparent text-muted-foreground',
        accent: 'border-primary/40 bg-primary/10 text-primary',
        success: 'border-success/40 bg-success/10 text-success',
        warning: 'border-warning/40 bg-warning/10 text-warning',
        destructive: 'border-destructive/40 bg-destructive/10 text-destructive',
        solid: 'border-transparent bg-muted text-foreground',
      },
    },
    defaultVariants: { variant: 'default' },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>, VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}
