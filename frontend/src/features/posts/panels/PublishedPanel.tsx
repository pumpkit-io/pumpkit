import { Button } from '@/components/ui/button';
import type { PostDetail } from '@/services/postService';
import type { ScheduledPost } from '@/services/scheduledPostService';
import { CopyPostButton } from '../CopyPostButton';
import { formatWhen, sourceVersionLabel } from './panelFacts';
import { DestinationName, Facts, Panel } from './panelParts';

/** A Published Post is finished: a record of where and when, and the way to it on X. */
export function PublishedPanel({
  post,
  scheduledPost,
  shownText,
}: {
  post: PostDetail;
  scheduledPost: ScheduledPost;
  shownText: string;
}) {
  const version = sourceVersionLabel(post, scheduledPost);

  return (
    <Panel name="Published">
      <div className="space-y-1">
        <p className="font-sans text-base font-semibold text-foreground">
          Published {formatWhen(scheduledPost.publishedAt ?? scheduledPost.publishAt)}
        </p>
        <Facts
          items={[
            ...(version ? [version] : []),
            <DestinationName key="destination" scheduledPost={scheduledPost} />,
          ]}
        />
        {scheduledPost.community && (
          <p className="font-sans text-sm text-muted-foreground">
            {scheduledPost.shareWithFollowers
              ? 'Shared with your followers'
              : 'Not shared with your followers'}
          </p>
        )}
        <p className="font-sans text-sm text-muted-foreground">
          Published posts can&apos;t be changed. To say more, start a new Post.
        </p>
      </div>
      <div className="flex flex-wrap items-center justify-end gap-2">
        <CopyPostButton text={shownText} />
        {scheduledPost.xPostUrl && (
          <Button asChild className="h-10 shrink-0">
            <a href={scheduledPost.xPostUrl} target="_blank" rel="noreferrer">
              View on X
            </a>
          </Button>
        )}
      </div>
    </Panel>
  );
}
