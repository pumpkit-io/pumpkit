import { DEFAULT_INSTANCE, type Instance } from '@/lib/instance';

/** For tests: an Instance that sells Plans and offers Google sign-in, without Operator details. */
export const SELLS_PLANS: Instance = {
  ...DEFAULT_INSTANCE,
  sells_plans: true,
  sign_in_methods: ['magic_link', 'google'],
};

/** For tests: a Self-hoster's Instance that gives a support address but no Operator details. */
export const WITH_SUPPORT_EMAIL: Instance = {
  ...DEFAULT_INSTANCE,
  support_email: 'help@example.org',
};

/** For tests: an Instance with Operator details, as the hosted Instance is configured. */
export const WITH_OPERATOR: Instance = {
  ...SELLS_PLANS,
  support_email: 'help@example.org',
  operator: {
    name: 'Example S.R.L.',
    vat_id: 'IT01234567890',
  },
};
