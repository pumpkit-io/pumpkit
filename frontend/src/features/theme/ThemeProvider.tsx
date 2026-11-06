import { createContext, useEffect, type ReactNode } from 'react';
import { registerSuperProperties } from '@/lib/analyticsConsent';

const DARK_THEME = { resolved: 'dark' } as const;

export const ThemeContext = createContext<typeof DARK_THEME | null>(null);

export function ThemeProvider({ children }: { children: ReactNode }) {
  useEffect(() => {
    document.documentElement.classList.add('dark');
    document.documentElement.style.colorScheme = 'dark';
    registerSuperProperties({ theme: 'dark', resolved_theme: 'dark' });
  }, []);

  return <ThemeContext.Provider value={DARK_THEME}>{children}</ThemeContext.Provider>;
}
