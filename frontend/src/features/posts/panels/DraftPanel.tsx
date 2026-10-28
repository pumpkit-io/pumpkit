import type { Version } from '@/services/postService';
import type { ScheduledPost } from '@/services/scheduledPostService';
import { CopyPostButton } from '../CopyPostButton';
import { FeedbackBar } from '../FeedbackBar';
import { PostToButton } from '../postTo/PostToButton';
import type { ShownPart } from '../shownText';
import type { FeedbackSending } from './feedback';
import { Panel } from './panelParts';

/** A Draft takes Feedback, and "Post to…" sends the Version on screen. */
export function DraftPanel({
  shownVersion,
  shownParts,
  shownText,
  latestVersion,
  feedback,
  onScheduled,
}: {
  shownVersion: Version;
  shownParts: ShownPart[];
  shownText: string;
  latestVersion: Version;
  feedback: FeedbackSending;
  onScheduled: (scheduledPost: ScheduledPost) => void;
}) {
  return (
    <Panel name="Draft">
      <FeedbackBar
        {...feedback}
        latestFormat={latestVersion.format}
        actions={
          <>
            <CopyPostButton text={shownText} />
            <PostToButton version={shownVersion} parts={shownParts} onDone={onScheduled} />
          </>
        }
      />
    </Panel>
  );
}
