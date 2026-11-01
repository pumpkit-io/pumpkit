import { apiService } from './apiService';

/** One of the User's Connected apps: an AI app they allowed to use Pumpkit as them. */
export interface AppConnection {
  id: string;
  appName: string;
  /** The domain the app's identity was checked against; null for an app that registered itself. */
  verifiedDomain: string | null;
  createdAt: string;
  lastUsedAt: string | null;
}

interface AppConnectionApi {
  id: string;
  app_name: string;
  verified_domain: string | null;
  created_at: string;
  last_used_at: string | null;
}

export const appConnectionService = {
  /** Newest first, without disconnected apps. */
  list: async (): Promise<AppConnection[]> => {
    const { data } = await apiService.get<{ data: AppConnectionApi[] }>('/app-connections');
    return data.data.map((c) => ({
      id: c.id,
      appName: c.app_name,
      verifiedDomain: c.verified_domain,
      createdAt: c.created_at,
      lastUsedAt: c.last_used_at,
    }));
  },

  /** The app's tokens stop working at once. Refused with a 404 when it's already disconnected. */
  disconnect: async (id: string): Promise<void> => {
    await apiService.delete(`/app-connections/${encodeURIComponent(id)}`);
  },
};
