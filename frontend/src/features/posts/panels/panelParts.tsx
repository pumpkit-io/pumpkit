import { Fragment, type ReactNode } from 'react';
import { InTheCommunity } from '@/features/scheduledPosts/InTheCommunity';
import type { ScheduledPost } from '@/services/scheduledPostService';

/** Where the Scheduled post goes or went. */
export function DestinationName({ scheduledPost }: { scheduledPost: ScheduledPost }) {
  return scheduledPost.community ? (
    <InTheCommunity community={scheduledPost.community} />
  ) : (
    <>Your profile</>
  );
}

/** Facts joined by a middle dot, as one line. */
export function Facts({ items }: { items: ReactNode[] }) {
  return (
    <p className="font-sans text-sm text-muted-foreground">
      {items.map((item, i) => (
        <Fragment key={i}>
          {i > 0 && ' · '}
          {item}
        </Fragment>
      ))}
    </p>
  );
}

/** The panel under the Version card, named for the Post's status. */
export function Panel({
  name,
  tone = 'default',
  children,
}: {
  name: string;
  tone?: 'default' | 'destructive';
  children: ReactNode;
}) {
  return (
    <section
      aria-label={name}
      className={
        tone === 'destructive'
          ? 'space-y-4 rounded-xl border border-destructive/40 bg-destructive/5 p-4 sm:p-5'
          : 'space-y-4 rounded-xl border border-border bg-card p-4 text-card-foreground sm:p-5'
      }
    >
      {children}
    </section>
  );
}
