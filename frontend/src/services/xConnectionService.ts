import { errorStatus } from './apiErrors';
import { apiService } from './apiService';
import { toUserProfile, type UserProfile, type UserProfileResponse } from './userService';

/** The User's permission for Pumpkit to publish on one X account. */
export interface XConnection {
  handle: string;
  /** The longest Scheduled post X accepts from this account, in X's weighted characters. */
  charLimit: number;
  needsReconnect: boolean;
  /** Scheduled posts for this X account not yet published; disconnecting makes them fail. */
  scheduledPostsWaiting: number;
  /** X's URL for the X account's photo; null when X gave none. */
  photoUrl: string | null;
  /** Whether to ask the User, who has no Photo, to use the X account's photo as theirs. */
  offerPhoto: boolean;
}

interface XConnectionApi {
  handle: string;
  char_limit: number;
  needs_reconnect: boolean;
  scheduled_posts_waiting: number;
  photo_url: string | null;
  offer_photo: boolean;
}

const toXConnection = (c: XConnectionApi): XConnection => ({
  handle: c.handle,
  charLimit: c.char_limit,
  needsReconnect: c.needs_reconnect,
  scheduledPostsWaiting: c.scheduled_posts_waiting,
  photoUrl: c.photo_url,
  offerPhoto: c.offer_photo,
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

  /** Copies the X account's photo into the User's Photo; answers with the updated profile. */
  acceptPhoto: async (): Promise<UserProfile> => {
    const { data } = await apiService.post<UserProfileResponse>('/x-connection/photo/use');
    return toUserProfile(data);
  },

  /** "Not now": stops offering the X account's photo for this X connection. */
  declinePhoto: async (): Promise<void> => {
    await apiService.post('/x-connection/photo/decline');
  },
};
