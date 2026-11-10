// The dev stack's Emulator seeds (docs/agents/dev-stack.md); scripts/dev-stack sets the variables.
// Throwaway data only. No oauth_clients, so the Google Emulator skips client and redirect URI checks.

import { pumpkitStripe } from './emulators/stripe.ts';
import { pumpkitX } from './emulators/x.ts';

export default {
  google: {
    users: [{ email: 'test@example.com', name: 'Test User' }],
  },
  services: {
    'pumpkit-x': {
      emulator: pumpkitX({
        clientId: 'pumpkit-dev-x',
        clientSecret: 'pumpkit-dev-x-secret',
        redirectUris: [process.env.DEV_PUBLIC_URL, process.env.DEV_STAGED_X_URL]
          .filter(Boolean)
          .map((url) => `${url}/oauth/x/callback`),
        apiUrl: process.env.X_API_URL ?? 'http://emulate:4002',
      }),
      seed: {
        users: [
          { id: '1001', username: 'ada', name: 'Ada', confirmed_email: 'ada@e2e-user.dev' },
          { id: '1002', username: 'grace', name: 'Grace', confirmed_email: 'grace@e2e-user.dev' },
          { id: '1003', username: 'no_email', name: 'No email' },
          {
            id: '2001',
            username: 'e2e_user',
            name: 'E2E User',
            confirmed_email: 'e2e@e2e-user.dev',
          },
          {
            id: '2002',
            username: 'e2e_newcomer',
            name: 'E2E Newcomer',
            confirmed_email: 'e2e-onboarding@e2e-user.dev',
          },
        ],
      },
    },
    // emulate refuses a custom service named after a built-in, so Stripe runs as pumpkit-stripe.
    'pumpkit-stripe': {
      emulator: pumpkitStripe({
        url: process.env.STRIPE_WEBHOOK_URL,
        secret: process.env.STRIPE_WEBHOOK_SECRET,
      }),
      seed: {
        products: [{ id: 'prod_pumpkit_pro', name: 'Pumpkit Pro' }],
        prices: [
          {
            id: 'price_pro_monthly',
            product: 'prod_pumpkit_pro',
            lookup_key: 'pumpkit_pro_monthly',
            currency: 'eur',
            unit_amount: 1500,
            recurring: { interval: 'month' },
          },
          {
            id: 'price_pro_yearly',
            product: 'prod_pumpkit_pro',
            lookup_key: 'pumpkit_pro_yearly',
            currency: 'eur',
            unit_amount: 15000,
            recurring: { interval: 'year' },
          },
          {
            id: 'price_top_up',
            product: 'prod_pumpkit_pro',
            lookup_key: 'pumpkit_top_up',
            currency: 'eur',
            unit_amount: 500,
          },
        ],
        // The customers and Subscriptions e2e/seed/ writes locally, so a sync from here agrees.
        // usage_user.py's switches between a Trial and an active Subscription, so it isn't seeded.
        customers: [
          { id: 'cus_e2e', email: 'e2e@e2e-user.dev', name: 'E2E User' },
          { id: 'cus_e2e_onboarding', email: 'e2e-onboarding@e2e-user.dev', name: 'E2E Newcomer' },
        ],
        subscriptions: [
          {
            id: 'sub_e2e',
            customer: 'cus_e2e',
            price: 'price_pro_monthly',
            status: 'active',
            created: '2026-10-01',
          },
          {
            id: 'sub_e2e_onboarding',
            customer: 'cus_e2e_onboarding',
            price: 'price_pro_monthly',
            status: 'active',
            created: '2026-10-01',
          },
        ],
      },
    },
  },
};
