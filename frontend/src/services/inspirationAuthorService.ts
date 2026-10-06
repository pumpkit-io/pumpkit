import { apiService } from './apiService';

/** An X account on the User's list whose posts set the style of their posts. */
export interface InspirationAuthor {
  /** Normalised: no @, lowercase. */
  handle: string;
  lastFetchedAt: string | null;
  postCount: number;
}

interface InspirationAuthorApi {
  handle: string;
  last_fetched_at: string | null;
  post_count: number;
}

const toAuthor = (a: InspirationAuthorApi): InspirationAuthor => ({
  handle: a.handle,
  lastFetchedAt: a.last_fetched_at,
  postCount: a.post_count,
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
