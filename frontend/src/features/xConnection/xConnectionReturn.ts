import { useEffect } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { showToast } from '@/components/Toaster';
import { savedReturn } from '@/lib/savedReturn';

function isPostPage(path: string): boolean {
  return /^\/posts\/[\w-]+$/.test(path);
}

/**
 * The Post page to come back to after X's consent screen. Without one, the X callback lands on
 * Settings.
 */
export const xConnectionReturn = savedReturn('x-connection-return', isPostPage);

/** What the X callback hands the page it returns to. */
export interface XConnectionNoticeState {
  xConnectionNotice?: string;
  xConnectionFailed?: boolean;
}

/** Shows the X callback's message on a Post page once, then drops it so a reload doesn't repeat it. */
export function useXConnectionNotice(): void {
  const location = useLocation();
  const navigate = useNavigate();
  const notice = (location.state as XConnectionNoticeState | null)?.xConnectionNotice;
  useEffect(() => {
    if (!notice) return;
    showToast(notice);
    navigate(location.pathname, { replace: true, state: null });
  }, [notice, location.pathname, navigate]);
}
