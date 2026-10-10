import { useEffect, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { Topbar } from '@/features/topbar/Topbar';
import { ScheduledPosts } from '@/features/scheduledPosts/ScheduledPosts';
import { XConnectionPanel } from '@/features/xConnection/XConnectionPanel';
import { XConnectionProvider } from '@/features/xConnection/XConnectionProvider';

/** What the X callback route leaves in the location state for this page. */
export interface ScheduledLocationState {
  xConnectionNotice?: string;
}

/** Takes the X callback's message once, then drops it so a reload doesn't show it again. */
function useXConnectionNotice(): string | null {
  const location = useLocation();
  const navigate = useNavigate();
  const [notice] = useState(
    () => (location.state as ScheduledLocationState | null)?.xConnectionNotice ?? null,
  );

  useEffect(() => {
    if (notice) navigate('.', { replace: true, state: null });
  }, [notice, navigate]);

  return notice;
}

/** Rendered inside AppLayout. */
export function Scheduled() {
  const notice = useXConnectionNotice();

  return (
    <>
      <Topbar title="Scheduled" />
      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-2xl space-y-10 px-4 py-8 sm:px-6">
          <XConnectionProvider>
            <XConnectionPanel notice={notice} />
            <ScheduledPosts />
          </XConnectionProvider>
        </div>
      </div>
    </>
  );
}
