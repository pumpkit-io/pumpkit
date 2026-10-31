import { apiService } from './apiService';

/** An X account the Instance knows, shared by all its Users (ADR 0019). */
export interface AuthorDirectoryEntry {
  /** Normalised: no @, lowercase. */
  handle: string;
  name: string | null;
  /** X's URL for the account's photo, loaded from X. */
  photoUrl: string | null;
  /** How many Users of the Instance have it in their Persona. */
  personaCount: number;
}

interface AuthorDirectoryEntryApi {
  handle: string;
  name: string | null;
  photo_url: string | null;
  persona_count: number;
}

export const authorDirectoryService = {
  list: async (): Promise<AuthorDirectoryEntry[]> => {
    const { data } = await apiService.get<{ data: AuthorDirectoryEntryApi[] }>('/author-directory');
    return data.data.map((e) => ({
      handle: e.handle,
      name: e.name,
      photoUrl: e.photo_url,
      personaCount: e.persona_count,
    }));
  },
};
