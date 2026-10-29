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
  feedback,
  onScheduled,
}: {
  postId: string;
  /** The Text, as the Version it came from. */
  textVersion: Version;
  parts: ShownPart[];
  origin: ReactNode;
  feedback: FeedbackSending;
  onScheduled: (scheduledPost: ScheduledPost) => void;
}) {
  const sender = useCreateFromText(postId);
  return (
    <FeedbackDock
      name="Draft"
      origin={origin}
      format={textVersion.format}
      feedback={feedback}
      postTo={
        <PostToButton
          format={textVersion.format}
          parts={parts}
          sender={sender}
          disabled={feedback.isWriting}
          onDone={onScheduled}
        />
      }
    />
  );
}
