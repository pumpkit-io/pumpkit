import { api } from './apiService';

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

  requestMagicLink: async (email: string): Promise<MessageResponse> => {
    const response = await api.post('/login/magic-link/request', { email });
    return response.data;
  },
};
