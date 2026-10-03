import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import type { ReactNode } from 'react';
import { ThemeProvider } from './ThemeProvider';
import { useTheme } from './useTheme';
import { storage } from '@/lib/storage';

vi.mock('@/lib/analytics', () => ({ registerSuperProperties: vi.fn() }));
import { registerSuperProperties } from '@/lib/analytics';

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

  it('defaults to system and follows a light OS', () => {
    mockSystemDark(false);
    const { result } = renderHook(() => useTheme(), { wrapper });
    expect(result.current.choice).toBe('system');
    expect(result.current.resolved).toBe('light');
    expect(document.documentElement.classList.contains('dark')).toBe(false);
  });

  it('follows a dark OS when choice is system', () => {
    mockSystemDark(true);
    const { result } = renderHook(() => useTheme(), { wrapper });
    expect(result.current.resolved).toBe('dark');
    expect(document.documentElement.classList.contains('dark')).toBe(true);
  });

  it('applies a stored explicit choice', () => {
    storage.set('theme', 'dark');
    const { result } = renderHook(() => useTheme(), { wrapper });
    expect(result.current.resolved).toBe('dark');
    expect(document.documentElement.classList.contains('dark')).toBe(true);
  });

  it('setChoice persists and re-resolves', () => {
    storage.set('theme', 'dark');
    const { result } = renderHook(() => useTheme(), { wrapper });
    act(() => result.current.setChoice('light'));
    expect(result.current.resolved).toBe('light');
    expect(storage.get('theme', 'system')).toBe('light');
    expect(document.documentElement.classList.contains('dark')).toBe(false);
  });

  it('reports theme super properties', () => {
    storage.set('theme', 'dark');
    renderHook(() => useTheme(), { wrapper });
    expect(registerSuperProperties).toHaveBeenCalledWith({ theme: 'dark', resolved_theme: 'dark' });
  });
});
