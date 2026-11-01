import { apiService } from './apiService';

/** What the consent page says about the app asking to connect. */
export interface ConsentApp {
  name: string;
  /** The domain the app's identity was checked against; null for an app that registered itself. */
  verifiedDomain: string | null;
  /** Where the app sends the User back to; null when `isLocal`. */
  redirectHost: string | null;
  /** The app runs on the User's computer: a loopback or app-scheme return address. */
  isLocal: boolean;
}

/** A pending authorization request, as the consent page shows it. */
export interface ConsentRequest {
  app: ConsentApp;
  scope: string;
  expiresAt: string;
}

interface ConsentRequestApi {
  client: {
    name: string;
    verified_domain: string | null;
    redirect_host: string | null;
    is_local: boolean;
  };
  scope: string;
  expires_at: string;
}

const path = (id: string) => `/oauth/authorizations/${encodeURIComponent(id)}`;

export const oauthConsentService = {
  /** Refused with a 404 when the request is unknown, expired or already decided. */
  get: async (id: string): Promise<ConsentRequest> => {
    const { data } = await apiService.get<ConsentRequestApi>(path(id));
    return {
      app: {
        name: data.client.name,
        verifiedDomain: data.client.verified_domain,
        redirectHost: data.client.redirect_host,
        isLocal: data.client.is_local,
      },
      scope: data.scope,
      expiresAt: data.expires_at,
    };
  },

  /** The app's return URL carrying the code. Refused with the subscribe 403 without access. */
  approve: async (id: string): Promise<string> => {
    const { data } = await apiService.post<{ redirect_url: string }>(`${path(id)}/approve`);
    return data.redirect_url;
  },

  /** The app's return URL carrying `access_denied`. */
  deny: async (id: string): Promise<string> => {
    const { data } = await apiService.post<{ redirect_url: string }>(`${path(id)}/deny`);
    return data.redirect_url;
  },
};
