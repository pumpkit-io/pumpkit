import { Notice } from '@/components/Notice';
import { destinationDraftOf } from '@/features/scheduledPosts/communities';
import type { ReachWarning, Version } from '@/services/postService';
import type { ScheduledPost } from '@/services/scheduledPostService';
import { PostToButton } from '../postTo/PostToButton';
import { useRetryFailed } from '../postTo/senders';
import type { ShownPart } from '../shownText';
import { FeedbackDock, type FeedbackSending } from './FeedbackDock';
import { formatWhen } from './panelFacts';

/** Feedback on a Failed Post, with why it didn't go out under it. */
export function FailedDock({
  scheduledPost,
  textVersion,
  feedback,
  restoreError,
  notice,
  warnings,
}: {
  scheduledPost: ScheduledPost;
  /** The Text, as the Version it came from. */
  textVersion: Version;
  feedback: FeedbackSending;
  restoreError?: string | null;
  /** The Text's Reach warnings, which a retry would carry. */
  warnings: ReachWarning[];
  /** Why the editor closed, under the reason; the Post page announces it. */
  notice: string | null;
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
          {notice && (
            <div className="pt-1.5">
              <Notice message={notice} announced={false} />
            </div>
          )}
        </div>
      }
      format={textVersion.format}
      feedback={feedback}
      restoreError={restoreError}
      warnings={warnings}
    />
  );
}

/** "Post to…" on a Failed Post, which retries its one Scheduled post with the Text on screen. */
export function FailedPostTo({
  postId,
  scheduledPost,
  oneIdeaADay,
  textVersion,
  retryParts,
  disabled,
  waitingFor,
  prepare,
  onRetried,
}: {
  postId: string;
  scheduledPost: ScheduledPost;
  oneIdeaADay: string | null;
  textVersion: Version;
  /** What the retry sends, the live Parts first. */
  retryParts: ShownPart[];
  disabled: boolean;
  waitingFor: string | null;
  /** Saves the User's last edit before "Post to…" opens. */
  prepare: () => Promise<boolean>;
  onRetried: (scheduledPost: ScheduledPost) => void;
}) {
  const sender = useRetryFailed(scheduledPost);
  return (
    <PostToButton
      postId={postId}
      format={textVersion.format}
      parts={retryParts}
      sender={sender}
      initialWhere={destinationDraftOf(scheduledPost)}
      oneIdeaADay={oneIdeaADay}
      disabled={disabled}
      waitingFor={waitingFor}
      prepare={prepare}
      onDone={onRetried}
    />
  );
}
