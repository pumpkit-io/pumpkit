import type { Version } from '@/services/postService';
import type { ScheduledPost } from '@/services/scheduledPostService';
import { PostToButton } from '../postTo/PostToButton';
import { useCreateFromText } from '../postTo/senders';
import type { ShownPart } from '../shownText';
import type { FeedbackSending } from './feedback';
import { FeedbackDock } from './FeedbackDock';

/** A Draft takes Feedback. */
export function DraftDock({
  textVersion,
  feedback,
  restoreError,
}: {
  /** The Text, as the Version it came from. */
  textVersion: Version;
  feedback: FeedbackSending;
  restoreError?: string | null;
}) {
  return (
    <FeedbackDock
      name="Draft"
      format={textVersion.format}
      feedback={feedback}
      restoreError={restoreError}
    />
  );
}

/** "Post to…" on a Draft, which sends the Text on screen. */
export function DraftPostTo({
  postId,
  textVersion,
  parts,
  disabled,
  prepare,
  onScheduled,
}: {
  postId: string;
  textVersion: Version;
  parts: ShownPart[];
  disabled: boolean;
  /** Saves the User's last edit before "Post to…" opens. */
  prepare: () => Promise<boolean>;
  onScheduled: (scheduledPost: ScheduledPost) => void;
}) {
  const sender = useCreateFromText(postId);
  return (
    <PostToButton
      format={textVersion.format}
      parts={parts}
      sender={sender}
      disabled={disabled}
      prepare={prepare}
      onDone={onScheduled}
    />
  );
}
