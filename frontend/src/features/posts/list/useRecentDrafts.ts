import { useEffect, useState } from 'react';
import { postService, type PostListItem } from '@/services/postService';
import { draftListItem, recentDraftIds } from './recentDrafts';

/**
 * The Drafts under Recently opened, most recently opened first, or null until every one has
 * answered. A Post scheduled, deleted or failing to load since is left out.
 */
export function useRecentDrafts(): PostListItem[] | null {
  const [drafts, setDrafts] = useState<PostListItem[] | null>(null);

  useEffect(() => {
    let live = true;
    void Promise.allSettled(recentDraftIds().map((id) => postService.get(id))).then((answers) => {
      if (!live) return;
      setDrafts(
        answers.flatMap((answer) => {
          if (answer.status !== 'fulfilled' || answer.value.status !== 'draft') return [];
          const item = draftListItem(answer.value);
          return item ? [item] : [];
        }),
      );
    });
    return () => {
      live = false;
    };
  }, []);

  return drafts;
}
