import { destinationDraftOf } from '@/features/scheduledPosts/communities';
import type { Version } from '@/services/postService';
import type { ScheduledPost } from '@/services/scheduledPostService';
import { PostToButton } from '../postTo/PostToButton';
import { useRetryFailed } from '../postTo/senders';
import type { ShownPart } from '../shownText';
import type { FeedbackSending } from './feedback';
import { FeedbackDock } from './FeedbackDock';
import { formatWhen } from './panelFacts';

/** Feedback on a Failed Post, with why it didn't go out under it. */
export function FailedDock({
  scheduledPost,
  textVersion,
  feedback,
  restoreError,
}: {
  scheduledPost: ScheduledPost;
  /** The Text, as the Version it came from. */
  textVersion: Version;
  feedback: FeedbackSending;
  restoreError?: string | null;
}) {
  return (
    <FeedbackDock
      name="Failed"
      reason={
        <div className="space-y-0.5 font-sans text-[13px] text-destructive">
          <p className="font-medium">
            This post didn’t go out. It was due {formatWhen(scheduledPost.publishAt)}.
          </p>
          {scheduledPost.failedReason && <p>{scheduledPost.failedReason}</p>}
        </div>
      }
      format={textVersion.format}
      feedback={feedback}
      restoreError={restoreError}
    />
  );
}

/** "Post to…" on a Failed Post, which retries its one Scheduled post with the Text on screen. */
export function FailedPostTo({
  scheduledPost,
  textVersion,
  retryParts,
  disabled,
  prepare,
  onRetried,
}: {
  scheduledPost: ScheduledPost;
  textVersion: Version;
  /** What the retry sends, the live Parts first. */
  retryParts: ShownPart[];
  disabled: boolean;
  /** Saves the User's last edit before "Post to…" opens. */
  prepare: () => Promise<boolean>;
  onRetried: (scheduledPost: ScheduledPost) => void;
}) {
  const sender = useRetryFailed(scheduledPost);
  return (
    <PostToButton
      format={textVersion.format}
      parts={retryParts}
      sender={sender}
      initialWhere={destinationDraftOf(scheduledPost)}
      disabled={disabled}
      prepare={prepare}
      onDone={onRetried}
    />
  );
}
