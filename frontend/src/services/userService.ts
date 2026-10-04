import { apiService } from './apiService';

export interface UserProfile {
  id: string;
  email: string;
  firstName: string | null;
  lastName: string | null;
  avatarUrl: string | null;
}

interface UserProfileResponse {
  id: string;
  email: string;
  first_name: string | null;
  last_name: string | null;
  avatar_data_url: string | null;
}

function fromResponse(data: UserProfileResponse): UserProfile {
  return {
    id: data.id,
    email: data.email,
    firstName: data.first_name,
    lastName: data.last_name,
    avatarUrl: data.avatar_data_url,
  };
}

export interface UserProfileUpdate {
  firstName?: string | null;
  lastName?: string | null;
  avatarUrl?: string | null;
}

export const userService = {
  fetchProfile: async (): Promise<UserProfile> => {
    const response = await apiService.get<UserProfileResponse>('/users/me');
    return fromResponse(response.data);
  },

  updateProfile: async (payload: UserProfileUpdate): Promise<UserProfile> => {
    // Map only fields the caller actually set, so the backend's
    // exclude_unset semantics are preserved (omitted ≠ null).
    const body: Record<string, string | null> = {};
    if ('firstName' in payload) body.first_name = payload.firstName ?? null;
    if ('lastName' in payload) body.last_name = payload.lastName ?? null;
    if ('avatarUrl' in payload) body.avatar_data_url = payload.avatarUrl ?? null;

    const response = await apiService.patch<UserProfileResponse>('/users/me', body);
    return fromResponse(response.data);
  },
};
