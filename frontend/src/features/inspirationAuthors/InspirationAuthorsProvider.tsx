import { createContext, type ReactNode } from 'react';
import { useInspirationAuthors } from './useInspirationAuthors';

type InspirationAuthorsValue = ReturnType<typeof useInspirationAuthors>;

export const InspirationAuthorsContext = createContext<InspirationAuthorsValue | null>(null);

/** One list of Inspiration authors for the panel that edits it and the writing area that needs it. */
export function InspirationAuthorsProvider({ children }: { children: ReactNode }) {
  const value = useInspirationAuthors();
  return (
    <InspirationAuthorsContext.Provider value={value}>
      {children}
    </InspirationAuthorsContext.Provider>
  );
}
