import { useId, type ReactNode } from 'react';
import { cn } from '@/lib/utils';

/** One card on the Settings page: a region named by its heading, with an optional lead line. */
export function SettingsCard({
  id,
  title,
  description,
  className,
  children,
}: {
  id?: string;
  title: string;
  description?: ReactNode;
  className?: string;
  children: ReactNode;
}) {
  const headingId = useId();
  return (
    <section
      id={id}
      aria-labelledby={headingId}
      className={cn(
        'scroll-mt-6 space-y-4 rounded-xl border border-border bg-card p-5 text-card-foreground sm:p-6',
        className,
      )}
    >
      <div className="space-y-1">
        <h2 id={headingId} className="font-sans text-base font-semibold text-foreground">
          {title}
        </h2>
        {description && <p className="font-sans text-sm text-muted-foreground">{description}</p>}
      </div>
      {children}
    </section>
  );
}
