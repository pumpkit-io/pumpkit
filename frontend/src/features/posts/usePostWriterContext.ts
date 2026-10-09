import { useContext } from 'react';
import { PostWriterContext } from './PostWriterProvider';

export function usePostWriterContext() {
  const ctx = useContext(PostWriterContext);
  if (!ctx) throw new Error('usePostWriterContext must be used within a PostWriterProvider');
  return ctx;
}
