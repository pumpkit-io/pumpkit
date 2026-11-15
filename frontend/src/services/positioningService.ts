import { apiService } from './apiService';

/** The longest Positioning, as `positioning/schemas.py` enforces with POSITIONING_MAX_CHARS. */
export const POSITIONING_MAX_CHARS = 4000;

/** The User's Positioning: who they are on X and what they post for, in their own words. */
export interface Positioning {
  text: string;
}

/** The draft of the Positioning the server keeps, unsaved, for a User with none (ADR 0030). */
export interface PositioningDraft {
  state: 'running' | 'ready' | 'failed';
  /** Set once the draft is ready. */
  text: string | null;
  /** Why there is no draft, a sentence for the User, once it failed. */
  reason: string | null;
}

/** What the Positioning panel opens with. */
export interface PositioningRead {
  /** Null until the User saves a Positioning. */
  text: string | null;
  /** Null once the User has a Positioning, and until a draft starts. */
  draft: PositioningDraft | null;
}

export const positioningService = {
  get: async (): Promise<PositioningRead> => {
    const { data } = await apiService.get<{
      text: string | null;
      draft: PositioningDraft | null;
    }>('/positioning');
    return { text: data.text, draft: data.draft };
  },

  /** Replaces any saved Positioning. The backend trims the text and refuses a blank one. */
  save: async (text: string): Promise<Positioning> => {
    const { data } = await apiService.put<{ text: string }>('/positioning', { text });
    return { text: data.text };
  },

  /**
   * Starts drafting the Positioning in the background, when the User has none and no draft
   * running or ready; `get` reads how it goes.
   */
  startDraft: async (): Promise<void> => {
    await apiService.post('/positioning/draft/start');
  },
};
