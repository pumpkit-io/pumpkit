import { apiService } from './apiService';

/** The longest Positioning, as `positioning/schemas.py` enforces with POSITIONING_MAX_CHARS. */
export const POSITIONING_MAX_CHARS = 4000;

/** The User's Positioning: who they are on X and what they post for, in their own words. */
export interface Positioning {
  text: string;
}

export const positioningService = {
  get: async (): Promise<Positioning | null> => {
    const { data } = await apiService.get<{ text: string | null }>('/positioning');
    return data.text === null ? null : { text: data.text };
  },

  /** Replaces any saved Positioning. The backend trims the text and refuses a blank one. */
  save: async (text: string): Promise<Positioning> => {
    const { data } = await apiService.put<{ text: string }>('/positioning', { text });
    return { text: data.text };
  },
};
