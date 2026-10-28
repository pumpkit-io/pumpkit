import type { Version } from '@/services/postService';
import type { ScheduledPost } from '@/services/scheduledPostService';
import { CopyPostButton } from '../CopyPostButton';
import { FeedbackBar } from '../FeedbackBar';
import type { FeedbackSending } from './feedback';
import { formatWhen } from './panelFacts';
import { Panel } from './panelParts';

/** Why the Post didn't go out, then Feedback for a Version X will take. */
export function FailedPanel({
  scheduledPost,
  shownText,
  latestVersion,
  feedback,
}: {
  scheduledPost: ScheduledPost;
  shownText: string;
  latestVersion: Version;
  feedback: FeedbackSending;
}) {
  return (
    <Panel name="Failed" tone="destructive">
      <div className="space-y-1">
        <p className="font-sans text-base font-semibold text-destructive">
          This Post didn’t go out. It was due {formatWhen(scheduledPost.publishAt)}.
        </p>
        {scheduledPost.failedReason && (
          <p className="font-sans text-sm text-foreground">{scheduledPost.failedReason}</p>
        )}
      </div>
      <div className="border-t border-destructive/20 pt-4">
        <FeedbackBar
          {...feedback}
          latestFormat={latestVersion.format}
          actions={<CopyPostButton text={shownText} />}
        />
      </div>
    </Panel>
  );
}
