import { API_BASE_URL } from '@/lib/api';

/** What this Instance offers, from `GET /instance`, so one frontend build serves every Instance. */

export type SignInMethod = 'magic_link' | 'google';

export interface OperatorDetails {
  name: string;
  address: string;
  vat_id: string | null;
  rea: string | null;
  share_capital: string | null;
  pec: string | null;
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
}

// Offers only what needs no provider, since without /instance nothing says which are configured.
export const DEFAULT_INSTANCE: Instance = {
  app_name: 'Pumpkit',
  sells_plans: false,
  sign_in_methods: ['magic_link'],
  operator: null,
  support_email: null,
  analytics: null,
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
