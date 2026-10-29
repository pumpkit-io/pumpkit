import type { PostText, Version } from '@/services/postService';
import type { ScheduledPost } from '@/services/scheduledPostService';
import { CopyPostButton } from '../CopyPostButton';
import { FeedbackBar } from '../FeedbackBar';
import { PostToButton } from '../postTo/PostToButton';
import { useCreateFromText } from '../postTo/senders';
import { textParts } from '../shownText';
import type { FeedbackSending } from './feedback';
import { Panel } from './panelParts';

/** A Draft takes Feedback, and "Post to…" sends the Post's Text. */
export function DraftPanel({
  postId,
  text,
  shownText,
  latestVersion,
  feedback,
  onScheduled,
}: {
  postId: string;
  text: PostText;
  shownText: string;
  latestVersion: Version;
  feedback: FeedbackSending;
  onScheduled: (scheduledPost: ScheduledPost) => void;
}) {
  const sender = useCreateFromText(postId);
  return (
    <Panel name="Draft">
      <FeedbackBar
        {...feedback}
        latestFormat={latestVersion.format}
        actions={
          <>
            <CopyPostButton text={shownText} />
            <PostToButton
              text={text}
              parts={textParts(text)}
              sender={sender}
              onDone={onScheduled}
            />
          </>
        }
      />
    </Panel>
  );
}
