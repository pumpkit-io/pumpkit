import { apiService } from './apiService';

/** The places in a Persona, as `authors/mediator.py` enforces with MAX_INSPIRATION_AUTHORS. */
export const MAX_INSPIRATION_AUTHORS = 3;

/** An X account on the User's list whose posts set the style of their posts. */
export interface InspirationAuthor {
  /** Normalised: no @, lowercase. */
  handle: string;
  lastFetchedAt: string | null;
  postCount: number;
  /** X's URL for the author's photo, loaded from X; null until a fetch finds one. */
  photoUrl: string | null;
}

interface InspirationAuthorApi {
  handle: string;
  last_fetched_at: string | null;
  post_count: number;
  photo_url: string | null;
}

const toAuthor = (a: InspirationAuthorApi): InspirationAuthor => ({
  handle: a.handle,
  lastFetchedAt: a.last_fetched_at,
  postCount: a.post_count,
  photoUrl: a.photo_url,
});

export const inspirationAuthorService = {
  list: async (): Promise<InspirationAuthor[]> => {
    const { data } = await apiService.get<{ data: InspirationAuthorApi[] }>('/inspiration-authors');
    return data.data.map(toAuthor);
  },

  /** Fetches the handle's posts before answering, so it can take a few seconds. */
  add: async (handle: string): Promise<InspirationAuthor> => {
    const { data } = await apiService.post<InspirationAuthorApi>('/inspiration-authors', {
      handle,
    });
    return toAuthor(data);
  },

  /** Refused with a 429 carrying `retry_at` when the handle was fetched within the hour. */
  refresh: async (handle: string): Promise<InspirationAuthor> => {
    const { data } = await apiService.post<InspirationAuthorApi>(
      `/inspiration-authors/${encodeURIComponent(handle)}/refresh`,
    );
    return toAuthor(data);
  },

  remove: async (handle: string): Promise<void> => {
    await apiService.delete(`/inspiration-authors/${encodeURIComponent(handle)}`);
  },
};
