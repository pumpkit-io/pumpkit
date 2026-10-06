import * as React from 'react';
import * as SwitchPrimitive from '@radix-ui/react-switch';

import { cn } from '../../lib/utils';

export const Switch = React.forwardRef<
  React.ElementRef<typeof SwitchPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof SwitchPrimitive.Root>
>(({ className, ...props }, ref) => {
  return (
    <SwitchPrimitive.Root
      ref={ref}
      className={cn(
        'peer inline-flex h-5 w-10 shrink-0 cursor-pointer items-center rounded-full border border-transparent px-1 transition-colors duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:cursor-not-allowed disabled:opacity-50 motion-reduce:transition-none data-[state=checked]:bg-primary data-[state=unchecked]:bg-muted-foreground',
        className,
      )}
      {...props}
    >
      <SwitchPrimitive.Thumb className="pointer-events-none block h-4 w-4 rounded-full bg-background shadow-sm transition-transform duration-200 motion-reduce:transition-none data-[state=checked]:translate-x-4 data-[state=unchecked]:translate-x-0" />
    </SwitchPrimitive.Root>
  );
});
Switch.displayName = SwitchPrimitive.Root.displayName;
