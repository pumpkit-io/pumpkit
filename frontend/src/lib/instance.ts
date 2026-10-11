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

export const DEFAULT_INSTANCE: Instance = {
  app_name: 'Pumpkit',
  sells_plans: true,
  sign_in_methods: ['magic_link', 'google'],
  operator: null,
  analytics: null,
};

/**
 * Plain fetch, not the api client: apiService builds its lock name from the app slug at import.
 * An unreachable backend falls back to the default, which loads no analytics.
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
