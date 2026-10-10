import { useCallback } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { usePostWriterContext } from '@/features/posts/usePostWriterContext';
import { track } from '@/lib/analytics';
import { useSidebar } from './useSidebar';

export type NewPostSource = 'sidebar' | 'rail' | 'shortcut';

/**
 * New Post from the sidebar row, the rail or the shortcut, on Home whatever page it starts
 * from; refused while a Version is on its way.
 */
export function useNewPost() {
  const { isWriting, newPost } = usePostWriterContext();
  const { setMobileOpen } = useSidebar();
  const navigate = useNavigate();
  const { pathname } = useLocation();

  const start = useCallback(
    (source: NewPostSource) => {
      if (isWriting) return;
      track('sidebar_new_post_clicked', { source });
      if (pathname !== '/home') navigate('/home');
      newPost();
      setMobileOpen(false);
    },
    [isWriting, newPost, setMobileOpen, navigate, pathname],
  );

  return { start, disabled: isWriting };
}
