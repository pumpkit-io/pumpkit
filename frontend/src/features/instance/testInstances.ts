import { DEFAULT_INSTANCE, type Instance } from '@/lib/instance';

/** For tests: an Instance with Operator details, as the hosted Instance is configured. */
export const WITH_OPERATOR: Instance = {
  ...DEFAULT_INSTANCE,
  operator: {
    name: 'Example S.R.L.',
    address: 'Via Roma 1, Milano, Italy',
    vat_id: 'IT01234567890',
    rea: 'MI-123456',
    share_capital: '€10,000 fully paid in',
    pec: 'example@pec.it',
    support_email: 'help@example.org',
  },
};
