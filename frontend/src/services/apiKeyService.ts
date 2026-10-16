import { apiService } from './apiService';

/** A key a program such as Claude Code uses to act for the User. Never carries the secret. */
export interface ApiKey {
  id: string;
  name: string;
  /** The first characters of the secret, enough to tell keys apart. */
  prefix: string;
  createdAt: string;
  lastUsedAt: string | null;
}

/** The answer to creating a key: the only time the secret and the command are sent. */
export interface CreatedApiKey {
  apiKey: ApiKey;
  secret: string;
  claudeCommand: string;
}

interface ApiKeyApi {
  id: string;
  name: string;
  prefix: string;
  created_at: string;
  last_used_at: string | null;
}

const toApiKey = (k: ApiKeyApi): ApiKey => ({
  id: k.id,
  name: k.name,
  prefix: k.prefix,
  createdAt: k.created_at,
  lastUsedAt: k.last_used_at,
});

export const apiKeyService = {
  list: async (): Promise<ApiKey[]> => {
    const { data } = await apiService.get<{ data: ApiKeyApi[] }>('/api-keys');
    return data.data.map(toApiKey);
  },

  /** Refused with a 409 at 10 keys, and with the subscribe 403 when the User has no access. */
  create: async (name: string): Promise<CreatedApiKey> => {
    const { data } = await apiService.post<{
      api_key: ApiKeyApi;
      secret: string;
      claude_command: string;
    }>('/api-keys', { name });
    return {
      apiKey: toApiKey(data.api_key),
      secret: data.secret,
      claudeCommand: data.claude_command,
    };
  },

  revoke: async (id: string): Promise<void> => {
    await apiService.delete(`/api-keys/${encodeURIComponent(id)}`);
  },
};
