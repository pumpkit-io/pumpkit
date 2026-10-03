import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';

vi.mock('@/services/userService', () => ({
  userService: {
    fetchProfile: vi.fn().mockResolvedValue({ email: 'a@example.com', firstName: null, lastName: null, avatarUrl: null }),
  },
}));

import { AuthProvider, useAuth } from './AuthContext';
import { authService } from '@/services/authService';

const wrapper = ({ children }: { children: ReactNode }) => <AuthProvider>{children}</AuthProvider>;
const inMinutes = (m: number) => new Date(Date.now() + m * 60_000).toISOString();

describe('AuthProvider bootstrap', () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    vi.restoreAllMocks();
  });

  it('is unauthenticated without a stored token', async () => {
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.isAuthenticated).toBe(false);
  });

  it('trusts a fresh token without refreshing', async () => {
    localStorage.setItem('auth_token', 't');
    localStorage.setItem('token_expires_at', inMinutes(60));
    const refresh = vi.spyOn(authService, 'refreshToken');
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.isAuthenticated).toBe(true));
    expect(refresh).not.toHaveBeenCalled();
  });

  it('refreshes a near-expiry token on boot', async () => {
    localStorage.setItem('auth_token', 't');
    localStorage.setItem('token_expires_at', inMinutes(5));
    const refresh = vi.spyOn(authService, 'refreshToken').mockResolvedValue();
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.isAuthenticated).toBe(true));
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it('stays signed in when refresh fails but the token is still valid', async () => {
    localStorage.setItem('auth_token', 't');
    localStorage.setItem('token_expires_at', inMinutes(5));
    vi.spyOn(authService, 'refreshToken').mockRejectedValue(new Error('offline'));
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.isAuthenticated).toBe(true);
  });

  it('clears an expired token when refresh fails', async () => {
    localStorage.setItem('auth_token', 't');
    localStorage.setItem('token_expires_at', inMinutes(-5));
    vi.spyOn(authService, 'refreshToken').mockRejectedValue(new Error('401'));
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.isAuthenticated).toBe(false);
    expect(localStorage.getItem('auth_token')).toBeNull();
    expect(localStorage.getItem('token_expires_at')).toBeNull();
  });

  it('signs out when another tab removes the token', async () => {
    localStorage.setItem('auth_token', 't');
    localStorage.setItem('token_expires_at', inMinutes(60));
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.isAuthenticated).toBe(true));
    act(() => {
      localStorage.removeItem('auth_token');
      window.dispatchEvent(new StorageEvent('storage', { key: 'auth_token' }));
    });
    expect(result.current.isAuthenticated).toBe(false);
  });
});
