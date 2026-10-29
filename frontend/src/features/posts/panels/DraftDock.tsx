import type { ReactNode } from 'react';
import type { Version } from '@/services/postService';
import type { ScheduledPost } from '@/services/scheduledPostService';
import { PostToButton } from '../postTo/PostToButton';
import { useCreateFromVersion } from '../postTo/senders';
import type { ShownPart } from '../shownText';
import type { FeedbackSending } from './feedback';
import { FeedbackDock } from './FeedbackDock';

/** A Draft takes Feedback, and "Post to…" sends the Text on screen. */
export function DraftDock({
  textVersion,
  parts,
  origin,
  feedback,
  onScheduled,
}: {
  /** The Text, as the Version it came from. */
  textVersion: Version;
  parts: ShownPart[];
  origin: ReactNode;
  feedback: FeedbackSending;
  onScheduled: (scheduledPost: ScheduledPost) => void;
}) {
  const sender = useCreateFromVersion(textVersion.id);
  return (
    <FeedbackDock
      name="Draft"
      origin={origin}
      format={textVersion.format}
      feedback={feedback}
      postTo={
        <PostToButton
          version={textVersion}
          parts={parts}
          sender={sender}
          disabled={feedback.isWriting}
          onDone={onScheduled}
        />
      }
    />
  );
}
