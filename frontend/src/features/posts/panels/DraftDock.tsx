import type { ReactNode } from 'react';
import type { Version } from '@/services/postService';
import type { ScheduledPost } from '@/services/scheduledPostService';
import { PostToButton } from '../postTo/PostToButton';
import { useCreateFromText } from '../postTo/senders';
import type { ShownPart } from '../shownText';
import type { FeedbackSending } from './feedback';
import { FeedbackDock } from './FeedbackDock';

/** A Draft takes Feedback, and "Post to…" sends the Text on screen. */
export function DraftDock({
  postId,
  textVersion,
  parts,
  origin,
  tools,
  feedback,
  restoreError,
  prepare,
  onScheduled,
}: {
  postId: string;
  /** The Text, as the Version it came from. */
  textVersion: Version;
  parts: ShownPart[];
  origin: ReactNode;
  tools?: ReactNode;
  feedback: FeedbackSending;
  restoreError?: string | null;
  /** Saves the User's last edit before "Post to…" opens. */
  prepare: () => Promise<boolean>;
  onScheduled: (scheduledPost: ScheduledPost) => void;
}) {
  const sender = useCreateFromText(postId);
  return (
    <FeedbackDock
      name="Draft"
      origin={origin}
      tools={tools}
      format={textVersion.format}
      feedback={feedback}
      restoreError={restoreError}
      postTo={
        <PostToButton
          format={textVersion.format}
          parts={parts}
          sender={sender}
          disabled={feedback.isWriting}
          prepare={prepare}
          onDone={onScheduled}
        />
      }
    />
  );
}
