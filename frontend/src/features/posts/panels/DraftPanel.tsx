import { FinalToXActions } from '@/features/scheduledPosts/FinalToX';
import type { Version } from '@/services/postService';
import type { ScheduledPost } from '@/services/scheduledPostService';
import { CopyPostButton } from '../CopyPostButton';
import { FeedbackBar } from '../FeedbackBar';
import type { FeedbackSending } from './feedback';
import { Panel } from './panelParts';

/**
 * A Draft takes Feedback. Schedule and Post now send the Version on screen until the
 * "Post to…" dialog replaces them.
 */
export function DraftPanel({
  shownVersion,
  shownText,
  latestVersion,
  feedback,
  onScheduled,
}: {
  shownVersion: Version;
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
            <FinalToXActions version={shownVersion} onCreated={onScheduled} />
          </>
        }
      />
    </Panel>
  );
}
