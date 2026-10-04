import { api, performRefresh } from './apiService';

export interface MessageResponse {
  message: string;
}

export interface GoogleLoginUrlResponse {
  authorization_url: string;
}

export const authService = {
  getGoogleLoginUrl: async (): Promise<GoogleLoginUrlResponse> => {
    const response = await api.get('/login/google');
    return { authorization_url: response.data.url };
  },

  logout: async (): Promise<void> => {
    try {
      await api.post('/logout');
    } catch {
      // Continue with local logout even if server call fails
    }

    localStorage.removeItem('auth_token');
    localStorage.removeItem('token_expires_at');
  },

  isAuthenticated: (): boolean => {
    // The presence of an access token is the source of truth. If we have
    // expiration metadata too, also reject obviously expired tokens. Without
    // expiration metadata (e.g., when the OAuth callback didn't include it),
    // trust the token — the server will reject it on the next API call if
    // it's actually expired, and the response interceptor will refresh.
    const token = localStorage.getItem('auth_token');
    if (!token) return false;
    const expiresAt = localStorage.getItem('token_expires_at');
    if (!expiresAt) return true;
    return new Date(expiresAt).getTime() > Date.now();
  },

  getToken: (): string | null => {
    return localStorage.getItem('auth_token');
  },

  needsRefresh: (): boolean => {
    const expiresAt = localStorage.getItem('token_expires_at');
    if (!expiresAt) return false;

    const expirationTime = new Date(expiresAt).getTime();
    const currentTime = Date.now();
    const refreshThreshold = 10 * 60 * 1000;

    return expirationTime <= currentTime + refreshThreshold;
  },

  refreshToken: async (): Promise<void> => {
    // All refresh paths funnel through performRefresh, which combines:
    //   - Per-tab in-flight dedup
    //   - Cross-tab serialization via navigator.locks
    //   - Inside-lock check that skips the network call if another tab just refreshed
    // This guarantees /refresh-token is never called in parallel — required by
    // the backend's refresh-token rotation + theft-detection semantics.
    await performRefresh();
  },

  getTokenExpiration: (): Date | null => {
    const expiresAt = localStorage.getItem('token_expires_at');
    return expiresAt ? new Date(expiresAt) : null;
  },

  requestMagicLink: async (email: string): Promise<MessageResponse> => {
    const response = await api.post('/login/magic-link/request', { email });
    return response.data;
  },
};
