import { API_BASE_URL } from '@/lib/api';

/** What this Instance offers, from `GET /instance`, so one frontend build serves every Instance. */

export type SignInMethod = 'magic_link' | 'google';

export interface OperatorDetails {
  name: string;
  vat_id: string | null;
}

export interface AnalyticsSettings {
  key: string;
  host: string;
  ui_host: string;
}

export interface Instance {
  app_name: string;
  sells_plans: boolean;
  sign_in_methods: SignInMethod[];
  operator: OperatorDetails | null;
  /** Where the support link sends Users' email; null hides it. */
  support_email: string | null;
  analytics: AnalyticsSettings | null;
  /** False on an Instance without X's app keys: Onboarding skips its X step, and no page offers to connect X. */
  x_connection: boolean;
  /** The MCP endpoint at `PUBLIC_URL`, which differs from the browser's origin behind a tunnel. */
  mcp_url: string | null;
}

// Offers only what needs no provider, since without /instance nothing says which are configured.
export const DEFAULT_INSTANCE: Instance = {
  app_name: 'Pumpkit',
  sells_plans: false,
  sign_in_methods: ['magic_link'],
  operator: null,
  support_email: null,
  analytics: null,
  x_connection: false,
  mcp_url: null,
};

/**
 * Plain fetch, not the api client: apiService builds its lock name from the app slug at import.
 * An unreachable backend or an error answer falls back to DEFAULT_INSTANCE.
 */
export async function fetchInstance(): Promise<Instance> {
  try {
    const response = await fetch(`${API_BASE_URL}/instance`);
    if (!response.ok) throw new Error(`GET /instance answered ${response.status}`);
    return (await response.json()) as Instance;
  } catch (error) {
    console.error('[instance] using defaults:', error);
    return DEFAULT_INSTANCE;
  }
}
