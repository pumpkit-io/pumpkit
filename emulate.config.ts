// The dev stack's Emulator seeds (docs/agents/dev-stack.md); scripts/dev-stack sets the variables.
// Throwaway data only. No oauth_clients, so the Google Emulator skips client and redirect URI checks.

const webhookUrl = process.env.STRIPE_WEBHOOK_URL;
const webhookSecret = process.env.STRIPE_WEBHOOK_SECRET;

export default {
  google: {
    users: [{ email: 'test@example.com', name: 'Test User' }],
  },
  stripe: {
    // The customer of e2e/seed/seed_user.py's Subscription. emulate already seeds test@example.com,
    // and a second customer with that email would be skipped.
    customers: [{ id: 'cus_e2e', email: 'e2e@e2e-user.dev', name: 'E2E User' }],
    // emulate 0.13.0 seeds one-off prices with no lookup key, and has no subscriptions,
    // so Plans and sub_e2e can't be seeded and the Plan catalog comes back empty.
    products: [{ name: 'Pumpkit Pro', description: 'Throwaway dev product' }],
    prices: [
      { id: 'price_pro_monthly', product_name: 'Pumpkit Pro', currency: 'eur', unit_amount: 1500 },
      { id: 'price_pro_yearly', product_name: 'Pumpkit Pro', currency: 'eur', unit_amount: 15000 },
      { id: 'price_top_up', product_name: 'Pumpkit Pro', currency: 'eur', unit_amount: 500 },
    ],
    webhooks: webhookUrl ? [{ url: webhookUrl, events: ['*'], secret: webhookSecret }] : [],
  },
};
