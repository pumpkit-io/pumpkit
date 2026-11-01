import type { ReactNode } from 'react';
import { ArrowRight } from 'lucide-react';

/**
 * A button label whose arrow appears when an ancestor named `group/cta` is hovered or focused.
 * The arrow's slot is always reserved and the label rests half a slot to the right, so the
 * button never resizes and the text and arrow stay centered together.
 */
export function ArrowLabel({ children }: { children: ReactNode }) {
  return (
    <span className="inline-flex translate-x-[0.75em] items-center transition-transform duration-200 group-hover/cta:translate-x-0 group-focus-visible/cta:translate-x-0 motion-reduce:transition-none">
      {children}
      <ArrowRight
        aria-hidden
        className="ml-[0.4em] size-[1.1em] opacity-0 transition-opacity duration-200 group-hover/cta:opacity-100 group-focus-visible/cta:opacity-100 motion-reduce:transition-none"
      />
    </span>
  );
}
