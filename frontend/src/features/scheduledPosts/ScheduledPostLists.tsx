import { ErrorBanner } from '@/components/ErrorBanner';
import type { ScheduledPost } from '@/services/scheduledPostService';

const dateTime = new Intl.DateTimeFormat('en', { dateStyle: 'medium', timeStyle: 'short' });

function ListSection({
  id,
  title,
  children,
}: {
  id: string;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section aria-labelledby={id} className="space-y-3">
      <h2 id={id} className="font-sans text-base font-semibold text-foreground">
        {title}
      </h2>
      {children}
    </section>
  );
}

function PostText({ text }: { text: string }) {
  return (
    <p className="whitespace-pre-wrap break-words font-sans text-sm text-foreground">{text}</p>
  );
}

const LIST = 'divide-y divide-border rounded-lg border border-border';
const ITEM = 'space-y-1.5 px-4 py-3';

/** Published Scheduled posts with a link to X, and Failed ones with their reason. */
export function ScheduledPostLists({
  scheduledPosts,
  loadFailed,
}: {
  scheduledPosts: ScheduledPost[] | undefined;
  loadFailed: boolean;
}) {
  const published = (scheduledPosts ?? []).filter((p) => p.state === 'published');
  const failed = (scheduledPosts ?? []).filter((p) => p.state === 'failed');

  return (
    <>
      {failed.length > 0 && (
        <ListSection id="failed-heading" title="Failed">
          <ul className={LIST}>
            {failed.map((post) => (
              <li key={post.id} className={ITEM}>
                <PostText text={post.text} />
                <p className="font-sans text-xs text-red-700 dark:text-red-300">
                  {post.failedReason}
                </p>
              </li>
            ))}
          </ul>
        </ListSection>
      )}
      <ListSection id="published-heading" title="Published">
        {loadFailed ? (
          <ErrorBanner message="Couldn't load your Scheduled posts. Reload the page to try again." />
        ) : scheduledPosts === undefined ? (
          <p role="status" className="font-sans text-sm text-muted-foreground">
            Loading your Scheduled posts…
          </p>
        ) : published.length === 0 ? (
          <p className="font-sans text-sm text-muted-foreground">
            Nothing published yet. Posts you publish show up here with a link to X.
          </p>
        ) : (
          <ul className={LIST}>
            {published.map((post) => (
              <li key={post.id} className={ITEM}>
                <PostText text={post.text} />
                <p className="flex flex-wrap gap-x-3 font-sans text-xs text-muted-foreground">
                  {post.publishedAt && (
                    <span>Published {dateTime.format(new Date(post.publishedAt))}</span>
                  )}
                  {post.xPostUrl && (
                    <a
                      href={post.xPostUrl}
                      target="_blank"
                      rel="noreferrer"
                      className="font-medium text-foreground underline underline-offset-2"
                    >
                      View on X
                    </a>
                  )}
                </p>
              </li>
            ))}
          </ul>
        )}
      </ListSection>
    </>
  );
}
