/** What this Instance offers, from `GET /instance`, so one frontend build serves every Instance. */

export type SignInMethod = 'magic_link' | 'google';

export interface OperatorDetails {
  name: string;
  address: string;
  vat_id: string | null;
  rea: string | null;
  share_capital: string | null;
  pec: string | null;
  support_email: string;
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
  analytics: AnalyticsSettings | null;
}

// Offers only what needs no provider, since without /instance nothing says which are configured.
export const DEFAULT_INSTANCE: Instance = {
  app_name: 'Pumpkit',
  sells_plans: false,
  sign_in_methods: ['magic_link'],
  operator: null,
  analytics: null,
};

/**
 * Plain fetch, not the api client: apiService builds its lock name from the app slug at import.
 * An unreachable backend or an error answer falls back to DEFAULT_INSTANCE.
 */
export async function fetchInstance(): Promise<Instance> {
  try {
    const response = await fetch(`${import.meta.env.VITE_API_URL}/instance`);
    if (!response.ok) throw new Error(`GET /instance answered ${response.status}`);
    return (await response.json()) as Instance;
  } catch (error) {
    console.error('[instance] using defaults:', error);
    return DEFAULT_INSTANCE;
  }
}
