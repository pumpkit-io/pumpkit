import { useContext } from 'react';
import { PostCountsContext } from './PostCountsProvider';

export function usePostCounts() {
  const ctx = useContext(PostCountsContext);
  if (!ctx) throw new Error('usePostCounts must be used within a PostCountsProvider');
  return ctx;
}
