import type { ReactNode } from 'react';
import { destinationDraftOf } from '@/features/scheduledPosts/communities';
import type { Version } from '@/services/postService';
import type { ScheduledPost } from '@/services/scheduledPostService';
import { PostToButton } from '../postTo/PostToButton';
import { useRetryFailed } from '../postTo/senders';
import type { ShownPart } from '../shownText';
import type { FeedbackSending } from './feedback';
import { FeedbackDock } from './FeedbackDock';
import { formatWhen } from './panelFacts';

/**
 * Why the Post didn't go out, then Feedback, and "Post to…", which retries the Post's one
 * Scheduled post with the Text on screen.
 */
export function FailedDock({
  scheduledPost,
  textVersion,
  retryParts,
  origin,
  tools,
  feedback,
  restoreError,
  prepare,
  onRetried,
}: {
  scheduledPost: ScheduledPost;
  /** The Text, as the Version it came from. */
  textVersion: Version;
  /** What the retry sends, the live Parts first. */
  retryParts: ShownPart[];
  origin: ReactNode;
  tools?: ReactNode;
  feedback: FeedbackSending;
  restoreError?: string | null;
  /** Saves the User's last edit before "Post to…" opens. */
  prepare: () => Promise<boolean>;
  onRetried: (scheduledPost: ScheduledPost) => void;
}) {
  const sender = useRetryFailed(scheduledPost);
  return (
    <FeedbackDock
      name="Failed"
      reason={
        <div className="space-y-0.5 font-sans text-[13px] text-destructive">
          <p className="font-medium">
            This Post didn’t go out. It was due {formatWhen(scheduledPost.publishAt)}.
          </p>
          {scheduledPost.failedReason && <p>{scheduledPost.failedReason}</p>}
        </div>
      }
      origin={origin}
      tools={tools}
      format={textVersion.format}
      feedback={feedback}
      restoreError={restoreError}
      postTo={
        <PostToButton
          format={textVersion.format}
          parts={retryParts}
          sender={sender}
          initialWhere={destinationDraftOf(scheduledPost)}
          disabled={feedback.isWriting}
          prepare={prepare}
          onDone={onRetried}
        />
      }
    />
  );
}
