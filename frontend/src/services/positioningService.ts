import { apiService } from './apiService';

/** The longest Positioning, as `positioning/schemas.py` enforces with POSITIONING_MAX_CHARS. */
export const POSITIONING_MAX_CHARS = 4000;

/** The User's Positioning: who they are on X and what they post for, in their own words. */
export interface Positioning {
  text: string;
}

/** What the Positioning panel opens with. */
export interface PositioningRead {
  /** Null until the User saves a Positioning. */
  text: string | null;
  /** False once the User has used up today's drafts. */
  canDraft: boolean;
}

/** A draft of the Positioning from the User's X profile, or why none could be made. */
export interface PositioningDraft {
  text: string | null;
  /** A sentence for the User when `text` is null. */
  reason: string | null;
  canDraft: boolean;
}

export const positioningService = {
  get: async (): Promise<PositioningRead> => {
    const { data } = await apiService.get<{ text: string | null; can_draft: boolean }>(
      '/positioning',
    );
    return { text: data.text, canDraft: data.can_draft };
  },

  /** Replaces any saved Positioning. The backend trims the text and refuses a blank one. */
  save: async (text: string): Promise<Positioning> => {
    const { data } = await apiService.put<{ text: string }>('/positioning', { text });
    return { text: data.text };
  },

  /** Saves nothing. Refused with a 429 once the User has used up today's drafts. */
  draft: async (): Promise<PositioningDraft> => {
    const { data } = await apiService.post<{
      text: string | null;
      reason: string | null;
      can_draft: boolean;
    }>('/positioning/draft');
    return { text: data.text, reason: data.reason, canDraft: data.can_draft };
  },
};
