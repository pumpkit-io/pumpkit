import { useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { track } from '@/lib/analytics';
import { useSidebar } from './useSidebar';

export type NewPostSource = 'sidebar' | 'shortcut';

/** New post from the sidebar or the shortcut: an empty /new from any page, /new included. */
export function useNewPost() {
  const { setMobileOpen } = useSidebar();
  const navigate = useNavigate();

  const start = useCallback(
    (source: NewPostSource) => {
      navigate('/new');
      setMobileOpen(false);
      track('sidebar_new_post_clicked', { source });
    },
    [setMobileOpen, navigate],
  );

  return { start };
}
