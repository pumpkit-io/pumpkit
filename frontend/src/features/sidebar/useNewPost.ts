import { useCallback } from 'react';
import { usePostWriterContext } from '@/features/posts/usePostWriterContext';
import { track } from '@/lib/analytics';
import { useSidebar } from './useSidebar';

export type NewPostSource = 'sidebar' | 'rail' | 'shortcut';

/** New Post from the sidebar row, the rail or the shortcut; refused while a Version is on its way. */
export function useNewPost() {
  const { isWriting, newPost } = usePostWriterContext();
  const { setMobileOpen } = useSidebar();

  const start = useCallback(
    (source: NewPostSource) => {
      if (isWriting) return;
      track('sidebar_new_post_clicked', { source });
      newPost();
      setMobileOpen(false);
    },
    [isWriting, newPost, setMobileOpen],
  );

  return { start, disabled: isWriting };
}
