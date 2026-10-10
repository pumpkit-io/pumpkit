import { Composer } from './Composer';
import { ScheduledPostLists } from './ScheduledPostLists';
import { useScheduledPosts } from './useScheduledPosts';

/** The composer and the lists it adds to. Needs an XConnectionProvider above it. */
export function ScheduledPosts() {
  const { scheduledPosts, loadFailed, posting, error, postNow, schedule } = useScheduledPosts();

  return (
    <>
      <Composer posting={posting} error={error} onPostNow={postNow} onSchedule={schedule} />
      <ScheduledPostLists scheduledPosts={scheduledPosts} loadFailed={loadFailed} />
    </>
  );
}
