import { apiService } from './apiService';

/** The longest Positioning, as `positioning/schemas.py` enforces with POSITIONING_MAX_CHARS. */
export const POSITIONING_MAX_CHARS = 4000;

/** The User's Positioning: who they are on X and what they post for, in their own words. */
export interface Positioning {
  text: string;
  savedAt: string;
}

interface SavedPositioningApi {
  text: string;
  saved_at: string;
}

/** Both fields are null until the User saves a Positioning. */
type PositioningApi = SavedPositioningApi | { text: null; saved_at: null };

export const positioningService = {
  /** Null until the User saves a Positioning. */
  get: async (): Promise<Positioning | null> => {
    const { data } = await apiService.get<PositioningApi>('/positioning');
    if (data.text === null || data.saved_at === null) return null;
    return { text: data.text, savedAt: data.saved_at };
  },

  /** Replaces any saved Positioning. The backend trims the text and refuses a blank one. */
  save: async (text: string): Promise<Positioning> => {
    const { data } = await apiService.put<SavedPositioningApi>('/positioning', { text });
    return { text: data.text, savedAt: data.saved_at };
  },
};
