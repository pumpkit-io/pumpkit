import { useContext } from 'react';
import { XConnectionContext } from './XConnectionProvider';

export function useXConnectionContext() {
  const ctx = useContext(XConnectionContext);
  if (!ctx) {
    throw new Error('useXConnectionContext must be used within an XConnectionProvider');
  }
  return ctx;
}
