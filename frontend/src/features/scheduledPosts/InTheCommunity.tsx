import type { Community } from '@/services/scheduledPostService';

/** "In the Community" and its name, or else its ID, linking to it on X. */
export function InTheCommunity({ community }: { community: Community }) {
  return (
    <>
      In the Community{' '}
      <a
        href={community.url}
        target="_blank"
        rel="noreferrer"
        className="font-medium text-foreground underline underline-offset-2"
      >
        {community.name ?? community.id}
      </a>
    </>
  );
}
