import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { renderHook } from '@testing-library/react';
import type { ReactNode } from 'react';
import { ThemeProvider } from './ThemeProvider';
import { useTheme } from './useTheme';
import { storage } from '@/lib/storage';

vi.mock('@/lib/analyticsConsent', () => ({ registerSuperProperties: vi.fn() }));
import { registerSuperProperties } from '@/lib/analyticsConsent';

function wrapper({ children }: { children: ReactNode }) {
  return <ThemeProvider>{children}</ThemeProvider>;
}

function mockSystemDark(dark: boolean) {
  return vi.spyOn(window, 'matchMedia').mockImplementation(
    (query: string) =>
      ({
        matches: dark && query.includes('dark'),
        media: query,
        onchange: null,
        addListener: () => {},
        removeListener: () => {},
        addEventListener: () => {},
        removeEventListener: () => {},
        dispatchEvent: () => false,
      }) as MediaQueryList,
  );
}

describe('ThemeProvider', () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.classList.remove('dark');
    vi.mocked(registerSuperProperties).mockClear();
  });
  afterEach(() => vi.restoreAllMocks());

  it.each([false, true])('enforces dark mode when system dark mode is %s', (systemDark) => {
    mockSystemDark(systemDark);
    const { result } = renderHook(() => useTheme(), { wrapper });
    expect(result.current.resolved).toBe('dark');
    expect(document.documentElement).toHaveClass('dark');
    expect(document.documentElement.style.colorScheme).toBe('dark');
  });

  it.each(['light', 'system', 'dark'])('ignores a stored %s preference', (choice) => {
    mockSystemDark(false);
    storage.set('theme', choice);
    const { result, unmount } = renderHook(() => useTheme(), { wrapper });
    expect(result.current.resolved).toBe('dark');
    expect(document.documentElement).toHaveClass('dark');
    unmount();
    renderHook(() => useTheme(), { wrapper });
    expect(document.documentElement).toHaveClass('dark');
  });

  it('reports the enforced theme in analytics', () => {
    storage.set('theme', 'light');
    renderHook(() => useTheme(), { wrapper });
    expect(registerSuperProperties).toHaveBeenCalledWith({ theme: 'dark', resolved_theme: 'dark' });
  });
});
