import { destinationDraftOf } from '@/features/scheduledPosts/communities';
import type { PostText, Version } from '@/services/postService';
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
 * retries the Post's one Scheduled post with the Post's Text.
 */
export function FailedPanel({
  scheduledPost,
  text,
  retryParts,
  shownText,
  latestVersion,
  feedback,
  onRetried,
}: {
  scheduledPost: ScheduledPost;
  text: PostText;
  /** What the retry sends, the live Parts first. */
  retryParts: ShownPart[];
  shownText: string;
  latestVersion: Version;
  feedback: FeedbackSending;
  onRetried: (scheduledPost: ScheduledPost) => void;
}) {
  const sender = useRetryFailed(scheduledPost);
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
                text={text}
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
