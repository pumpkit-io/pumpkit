import { api } from './apiService';

export interface XSignInCompletion {
  state: string;
  code: string | null;
  error: string | null;
}

export const xSignInService = {
  async start(): Promise<string> {
    const response = await api.get('/login/x');
    return response.data.url;
  },
  async complete(data: XSignInCompletion): Promise<{ accessToken: string; expiresAt: string }> {
    const response = await api.post('/login/x/complete', data);
    return { accessToken: response.data.access_token, expiresAt: response.data.expires_at };
  },
};
