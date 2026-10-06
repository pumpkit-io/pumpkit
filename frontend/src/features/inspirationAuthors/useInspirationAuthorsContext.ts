import { useContext } from 'react';
import { InspirationAuthorsContext } from './InspirationAuthorsProvider';

export function useInspirationAuthorsContext() {
  const ctx = useContext(InspirationAuthorsContext);
  if (!ctx) {
    throw new Error(
      'useInspirationAuthorsContext must be used within an InspirationAuthorsProvider',
    );
  }
  return ctx;
}
