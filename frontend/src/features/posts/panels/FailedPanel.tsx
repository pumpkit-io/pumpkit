import { destinationDraftOf } from '@/features/scheduledPosts/communities';
import type { Version } from '@/services/postService';
import type { ScheduledPost } from '@/services/scheduledPostService';
import { CopyPostButton } from '../CopyPostButton';
import { FeedbackBar } from '../FeedbackBar';
import { PostToButton } from '../postTo/PostToButton';
import { useRetryFailed } from '../postTo/senders';
import type { ShownPart } from '../shownText';
import type { FeedbackSending } from './feedback';
import { formatWhen } from './panelFacts';
import { Panel } from './panelParts';

/**
 * Why the Post didn't go out, then Feedback for a Version X will take, and "Post to…", which
 * retries the Post's one Scheduled post with the Version on screen.
 */
export function FailedPanel({
  scheduledPost,
  shownVersion,
  retryParts,
  shownText,
  latestVersion,
  feedback,
  onRetried,
}: {
  scheduledPost: ScheduledPost;
  shownVersion: Version;
  /** What the retry sends, the live Parts first. */
  retryParts: ShownPart[];
  shownText: string;
  latestVersion: Version;
  feedback: FeedbackSending;
  onRetried: (scheduledPost: ScheduledPost) => void;
}) {
  const sender = useRetryFailed(scheduledPost, shownVersion.id);
  return (
    <Panel name="Failed" tone="destructive">
      <div className="space-y-1">
        <p className="font-sans text-base font-semibold text-destructive">
          This Post didn’t go out. It was due {formatWhen(scheduledPost.publishAt)}.
        </p>
        {scheduledPost.failedReason && (
          <p className="font-sans text-sm text-foreground">{scheduledPost.failedReason}</p>
        )}
      </div>
      <div className="border-t border-destructive/20 pt-4">
        <FeedbackBar
          {...feedback}
          latestFormat={latestVersion.format}
          actions={
            <>
              <CopyPostButton text={shownText} />
              <PostToButton
                version={shownVersion}
                parts={retryParts}
                sender={sender}
                initialWhere={destinationDraftOf(scheduledPost)}
                onDone={onRetried}
              />
            </>
          }
        />
      </div>
    </Panel>
  );
}
