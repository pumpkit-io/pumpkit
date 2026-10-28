import { Topbar } from '@/features/topbar/Topbar';
import { ScheduledPosts } from '@/features/scheduledPosts/ScheduledPosts';

/** Rendered inside AppLayout. */
export function Scheduled() {
  return (
    <>
      <Topbar title="Posts" />
      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-2xl space-y-10 px-4 py-8 sm:px-6">
          <ScheduledPosts />
        </div>
      </div>
    </>
  );
}
