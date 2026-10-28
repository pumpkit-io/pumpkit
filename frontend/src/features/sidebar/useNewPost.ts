import { useCallback } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { usePostWriterContext } from '@/features/posts/usePostWriterContext';
import { track } from '@/lib/analytics';
import { useSidebar } from './useSidebar';

export type NewPostSource = 'sidebar' | 'shortcut';

/**
 * New post from the sidebar or the shortcut: an empty /new from any page. While a Version is on
 * its way it only goes to /new, so the Post being written stays on screen.
 */
export function useNewPost() {
  const { isWriting, newPost } = usePostWriterContext();
  const { setMobileOpen } = useSidebar();
  const navigate = useNavigate();
  const { pathname } = useLocation();

  const start = useCallback(
    (source: NewPostSource) => {
      if (pathname !== '/new') navigate('/new');
      setMobileOpen(false);
      if (isWriting) return;
      track('sidebar_new_post_clicked', { source });
      newPost();
    },
    [isWriting, newPost, setMobileOpen, navigate, pathname],
  );

  return { start };
}
