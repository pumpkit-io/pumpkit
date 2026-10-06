import { useContext } from 'react';
import { SubscribedContext } from './SubscribedProvider';

export function useSubscribed() {
  const ctx = useContext(SubscribedContext);
  if (!ctx) {
    throw new Error('useSubscribed must be used within a SubscribedProvider');
  }
  return ctx;
}
