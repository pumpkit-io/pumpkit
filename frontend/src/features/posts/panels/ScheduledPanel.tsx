import { TIME_ZONE } from '@/features/scheduledPosts/localTime';
import type { PostDetail } from '@/services/postService';
import type { ScheduledPost } from '@/services/scheduledPostService';
import { CopyPostButton } from '../CopyPostButton';
import { formatWhen, sourceVersionLabel } from './panelFacts';
import { DestinationName, Facts, Panel } from './panelParts';

/** A Scheduled Post takes no Feedback: its text is set to go, and is edited instead. */
export function ScheduledPanel({
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
    <Panel name="Scheduled">
      <div className="space-y-1">
        <p className="font-sans text-base font-semibold text-foreground">
          Scheduled for {formatWhen(scheduledPost.publishAt)}
        </p>
        <Facts
          items={[
            ...(version ? [version] : []),
            <DestinationName key="destination" scheduledPost={scheduledPost} />,
            TIME_ZONE,
          ]}
        />
      </div>
      <div className="flex flex-wrap items-center justify-end gap-2">
        <CopyPostButton text={shownText} />
      </div>
    </Panel>
  );
}
