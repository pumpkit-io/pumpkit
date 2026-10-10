import { errorStatus } from './apiErrors';
import { apiService } from './apiService';

/** The User's permission for Pumpkit to publish on one X account. */
export interface XConnection {
  handle: string;
  /** The longest Scheduled post X accepts from this account, in X's weighted characters. */
  charLimit: number;
  needsReconnect: boolean;
}

interface XConnectionApi {
  handle: string;
  char_limit: number;
  needs_reconnect: boolean;
}

const toXConnection = (c: XConnectionApi): XConnection => ({
  handle: c.handle,
  charLimit: c.char_limit,
  needsReconnect: c.needs_reconnect,
});

export const xConnectionService = {
  /** Null when the User has no X connection. */
  get: async (): Promise<XConnection | null> => {
    try {
      const { data } = await apiService.get<XConnectionApi>('/x-connection');
      return toXConnection(data);
    } catch (e) {
      if (errorStatus(e) === 404) return null;
      throw e;
    }
  },

  /** X's consent screen URL; X sends the browser back to /oauth/x/callback. */
  startAuthorization: async (): Promise<string> => {
    const { data } = await apiService.post<{ url: string }>('/x-connection/authorizations');
    return data.url;
  },

  complete: async (code: string, state: string): Promise<XConnection> => {
    const { data } = await apiService.post<XConnectionApi>(
      '/x-connection/authorizations/complete',
      {
        code,
        state,
      },
    );
    return toXConnection(data);
  },

  disconnect: async (): Promise<void> => {
    await apiService.delete('/x-connection');
  },
};
