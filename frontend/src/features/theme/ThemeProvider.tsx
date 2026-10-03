import { createContext, useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import { storage } from '@/lib/storage';
import { registerSuperProperties } from '@/lib/analytics';

export type ThemeChoice = 'system' | 'light' | 'dark';
export type ResolvedTheme = 'light' | 'dark';

interface ThemeContextValue {
  choice: ThemeChoice;
  resolved: ResolvedTheme;
  setChoice: (choice: ThemeChoice) => void;
}

export const ThemeContext = createContext<ThemeContextValue | null>(null);

const DARK_QUERY = '(prefers-color-scheme: dark)';

function systemPrefersDark(): boolean {
  return typeof window !== 'undefined' && window.matchMedia(DARK_QUERY).matches;
}

function resolve(choice: ThemeChoice): ResolvedTheme {
  if (choice === 'system') return systemPrefersDark() ? 'dark' : 'light';
  return choice;
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [choice, setChoiceState] = useState<ThemeChoice>(() =>
    storage.get<ThemeChoice>('theme', 'system'),
  );
  const [resolved, setResolved] = useState<ResolvedTheme>(() => resolve(choice));

  // Follow OS changes while the choice is "system".
  useEffect(() => {
    if (choice !== 'system') {
      setResolved(choice);
      return;
    }
    const mq = window.matchMedia(DARK_QUERY);
    const apply = () => setResolved(mq.matches ? 'dark' : 'light');
    apply();
    mq.addEventListener('change', apply);
    return () => mq.removeEventListener('change', apply);
  }, [choice]);

  useEffect(() => {
    document.documentElement.classList.toggle('dark', resolved === 'dark');
  }, [resolved]);

  useEffect(() => {
    registerSuperProperties({ theme: choice, resolved_theme: resolved });
  }, [choice, resolved]);

  const setChoice = useCallback((next: ThemeChoice) => {
    storage.set('theme', next);
    setChoiceState(next);
  }, []);

  const value = useMemo(() => ({ choice, resolved, setChoice }), [choice, resolved, setChoice]);

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}
