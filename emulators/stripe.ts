// The dev stack's Stripe (docs/agents/dev-stack.md): an emulate custom Emulator serving only the calls
// backend/src/pumpkit/billing/gateway.py makes, in the shapes its recorded fixtures show.
// Loaded by emulate with Node's type stripping, so it keeps to erasable TypeScript and Node built-ins.

import { createHmac } from 'node:crypto';

type StripeObject = Record<string, any>;

interface State {
  products: Record<string, StripeObject>;
  prices: Record<string, StripeObject>;
  customers: Record<string, StripeObject>;
  subscriptions: Record<string, StripeObject>;
  checkoutSessions: Record<string, StripeObject>;
  paymentIntents: Record<string, StripeObject>;
  charges: Record<string, StripeObject>;
  invoices: Record<string, StripeObject>;
  portalSessions: Record<string, StripeObject>;
  // Idempotency-Key to the customer its first request created.
  idempotentCustomers: Record<string, string>;
}

interface Seed {
  products?: { id: string; name: string }[];
  prices?: {
    id: string;
    product: string;
    lookup_key: string;
    currency: string;
    unit_amount: number;
    recurring?: { interval: 'day' | 'week' | 'month' | 'year'; interval_count?: number };
  }[];
  customers?: { id: string; email: string; name?: string }[];
  subscriptions?: {
    id: string;
    customer: string;
    price: string;
    status: string;
    created: string;
  }[];
}

interface WebhookTarget {
  url?: string;
  secret?: string;
}

const OWNER = 'pumpkit-stripe';
const DAY = 24 * 60 * 60;
const INTERVAL_DAYS: Record<string, number> = { day: 1, week: 7, month: 30, year: 365 };

const now = () => Math.floor(Date.now() / 1000);
// Random, not counted: IDs outlive the Emulator's state in the backend's database.
const newId = (prefix: string) =>
  `${prefix}_${crypto.randomUUID().replaceAll('-', '').slice(0, 24)}`;

function emptyState(): State {
  return {
    products: {},
    prices: {},
    customers: {},
    subscriptions: {},
    checkoutSessions: {},
    paymentIntents: {},
    charges: {},
    invoices: {},
    portalSessions: {},
    idempotentCustomers: {},
  };
}

function periodEnd(start: number, price: StripeObject): number {
  const { interval, interval_count: count } = price.recurring;
  return start + INTERVAL_DAYS[interval] * (count ?? 1) * DAY;
}

function newSubscription(
  customer: string,
  price: StripeObject,
  quantity: number,
  trialDays: number | null,
): StripeObject {
  const created = now();
  const trialEnd = trialDays ? created + trialDays * DAY : null;
  return {
    id: newId('sub'),
    object: 'subscription',
    customer,
    status: trialEnd ? 'trialing' : 'active',
    created,
    start_date: created,
    billing_cycle_anchor: trialEnd ?? created,
    cancel_at: null,
    cancel_at_period_end: false,
    canceled_at: null,
    ended_at: null,
    trial_start: trialEnd ? created : null,
    trial_end: trialEnd,
    latest_invoice: null,
    metadata: {},
    livemode: false,
    items: {
      object: 'list',
      has_more: false,
      data: [
        {
          id: newId('si'),
          object: 'subscription_item',
          price,
          quantity,
          current_period_start: created,
          current_period_end: trialEnd ?? periodEnd(created, price),
        },
      ],
    },
  };
}

function seedState(seed: Seed): State {
  const state = emptyState();
  for (const p of seed.products ?? []) {
    state.products[p.id] = {
      id: p.id,
      object: 'product',
      name: p.name,
      active: true,
      metadata: {},
    };
  }
  for (const p of seed.prices ?? []) {
    state.prices[p.id] = {
      id: p.id,
      object: 'price',
      active: true,
      currency: p.currency,
      unit_amount: p.unit_amount,
      lookup_key: p.lookup_key,
      nickname: null,
      product: p.product,
      recurring: p.recurring ? { interval_count: 1, ...p.recurring } : null,
      type: p.recurring ? 'recurring' : 'one_time',
      created: now(),
      metadata: {},
      livemode: false,
    };
  }
  for (const c of seed.customers ?? []) {
    state.customers[c.id] = {
      id: c.id,
      object: 'customer',
      email: c.email,
      name: c.name ?? null,
      metadata: {},
    };
  }
  for (const s of seed.subscriptions ?? []) {
    const subscription = newSubscription(s.customer, state.prices[s.price], 1, null);
    subscription.id = s.id;
    subscription.status = s.status;
    subscription.created = subscription.start_date = Math.floor(Date.parse(s.created) / 1000);
    state.subscriptions[s.id] = subscription;
  }
  return state;
}

// Stripe's form encoding: `line_items[0][price]=x&metadata[k]=v` into nested objects and arrays.
function parseStripeParams(params: URLSearchParams): StripeObject {
  const out: StripeObject = {};
  for (const [key, value] of params) {
    const [head, ...rest] = key.replace(/\]/g, '').split('[');
    let node: StripeObject = out;
    const path = [head, ...rest];
    path.forEach((segment, i) => {
      const last = i === path.length - 1;
      const nextIsIndex = !last && /^\d*$/.test(path[i + 1]);
      if (last) {
        if (Array.isArray(node) && segment === '') node.push(value);
        else node[segment] = value;
      } else {
        node[segment] ??= nextIsIndex ? [] : {};
        node = node[segment];
      }
    });
  }
  return out;
}

async function bodyParams(c: any): Promise<StripeObject> {
  return parseStripeParams(new URLSearchParams(await c.req.text()));
}

function queryParams(c: any): StripeObject {
  return parseStripeParams(new URL(c.req.url).searchParams);
}

function list(url: string, data: StripeObject[]): StripeObject {
  return { object: 'list', url, has_more: false, data };
}

function notFound(c: any, what: string, id: string) {
  return c.json(
    {
      error: {
        type: 'invalid_request_error',
        code: 'resource_missing',
        message: `No such ${what}: '${id}'`,
      },
    },
    404,
  );
}

function escapeHtml(text: string): string {
  return text.replace(/[&<>"']/g, (ch) => `&#${ch.charCodeAt(0)};`);
}

function page(title: string, body: string): string {
  return `<!doctype html><html><head><meta charset="utf-8"><title>${escapeHtml(title)}</title>
<style>body{font-family:system-ui,sans-serif;max-width:32rem;margin:4rem auto;padding:0 1rem}
button{font:inherit;padding:.5rem 1rem;cursor:pointer}</style></head>
<body><p><small>Stripe Emulator (dev stack)</small></p><h1>${escapeHtml(title)}</h1>${body}</body></html>`;
}

// Stripe's scheme: HMAC-SHA256 of `<timestamp>.<body>` with the endpoint's signing secret.
function stripeSignature(secret: string, body: string): string {
  const timestamp = now();
  return `t=${timestamp},v1=${createHmac('sha256', secret).update(`${timestamp}.${body}`).digest('hex')}`;
}

export function pumpkitStripe(target: WebhookTarget) {
  return {
    kind: 'emulate.http',
    apiVersion: 1,
    name: OWNER,
    state: emptyState,
    validateSeed: (value: unknown) => seedState((value ?? {}) as Seed),
    setup({
      app,
      state,
      webhooks,
      baseUrl,
    }: {
      app: any;
      state: State;
      webhooks: any;
      baseUrl: string;
    }) {
      if (target.url) {
        webhooks.register({
          url: target.url,
          events: ['*'],
          active: true,
          secret: target.secret,
          owner: OWNER,
        });
      }
      webhooks.setHeaderFactory(
        ({ body, subscription }: { body: string; subscription: StripeObject }) => ({
          'Content-Type': 'application/json',
          'Stripe-Signature': stripeSignature(subscription.secret ?? '', body),
        }),
      );

      async function send(type: string, object: StripeObject): Promise<void> {
        const event = {
          id: newId('evt'),
          object: 'event',
          type,
          created: now(),
          livemode: false,
          data: { object },
        };
        await webhooks.dispatch(type, undefined, event, OWNER);
      }

      // An API call never waits for its webhook: the backend may hold the User's lock until the
      // call answers, and its webhook handler takes the same lock.
      function sendLater(type: string, object: StripeObject): void {
        void send(type, structuredClone(object)).catch(() => undefined);
      }

      function expandedPrice(price: StripeObject, expand: string[]): StripeObject {
        return expand.includes('data.product')
          ? { ...price, product: state.products[price.product] }
          : price;
      }

      function expandedSession(session: StripeObject, expand: string[]): StripeObject {
        if (!expand.includes('data.payment_intent.latest_charge') || !session.payment_intent)
          return session;
        const intent = state.paymentIntents[session.payment_intent];
        return {
          ...session,
          payment_intent: { ...intent, latest_charge: state.charges[intent.latest_charge] },
        };
      }

      app.get('/_pumpkit/webhook-deliveries', (c: any) =>
        c.json(
          webhooks
            .getDeliveries()
            .map((d: StripeObject) => ({
              event: d.event,
              status_code: d.status_code,
              success: d.success,
            })),
        ),
      );

      app.post('/v1/customers', async (c: any) => {
        const key = c.req.header('Idempotency-Key');
        if (key && state.idempotentCustomers[key])
          return c.json(state.customers[state.idempotentCustomers[key]]);
        const params = await bodyParams(c);
        const customer = {
          id: newId('cus'),
          object: 'customer',
          email: params.email ?? null,
          name: params.name ?? null,
          metadata: params.metadata ?? {},
          created: now(),
          livemode: false,
        };
        state.customers[customer.id] = customer;
        if (key) state.idempotentCustomers[key] = customer.id;
        sendLater('customer.created', customer);
        return c.json(customer);
      });

      app.get('/v1/prices', (c: any) => {
        const { lookup_keys: keys, active, expand = [] } = queryParams(c);
        const prices = Object.values(state.prices).filter(
          (p) =>
            (!keys || keys.includes(p.lookup_key)) &&
            (active === undefined || String(p.active) === active),
        );
        return c.json(
          list(
            '/v1/prices',
            prices.map((p) => expandedPrice(p, expand)),
          ),
        );
      });

      app.post('/v1/checkout/sessions', async (c: any) => {
        const params = await bodyParams(c);
        const [item] = params.line_items ?? [];
        if (!state.prices[item?.price]) return notFound(c, 'price', item?.price);
        const days = params.subscription_data?.trial_period_days;
        const session = {
          id: newId('cs_test'),
          object: 'checkout.session',
          mode: params.mode,
          status: 'open',
          payment_status: 'unpaid',
          customer: params.customer,
          client_reference_id: params.client_reference_id ?? null,
          metadata: params.metadata ?? {},
          success_url: params.success_url,
          cancel_url: params.cancel_url,
          created: now(),
          subscription: null,
          payment_intent: null,
          livemode: false,
          // Kept for completing the session; Stripe's own sessions expand line items instead.
          pumpkit_line_item: { price: item.price, quantity: Number(item.quantity ?? 1) },
          pumpkit_trial_days: days === undefined ? null : Number(days),
        };
        // The browser opens it, so it uses the advertised route, not the address the backend called.
        session.url = `${baseUrl}/checkout/${session.id}`;
        state.checkoutSessions[session.id] = session;
        return c.json(session);
      });

      app.get('/v1/checkout/sessions', (c: any) => {
        const { customer, status, expand = [] } = queryParams(c);
        const sessions = Object.values(state.checkoutSessions).filter(
          (s) => (!customer || s.customer === customer) && (!status || s.status === status),
        );
        return c.json(
          list(
            '/v1/checkout/sessions',
            sessions.map((s) => expandedSession(s, expand)),
          ),
        );
      });

      app.post('/v1/checkout/sessions/:id/expire', (c: any) => {
        const session = state.checkoutSessions[c.req.param('id')];
        if (!session) return notFound(c, 'checkout.session', c.req.param('id'));
        if (session.status !== 'open') {
          return c.json(
            {
              error: {
                type: 'invalid_request_error',
                message: `Only open sessions can be expired: ${session.id}`,
              },
            },
            400,
          );
        }
        session.status = 'expired';
        sendLater('checkout.session.expired', session);
        return c.json(session);
      });

      app.get('/checkout/:id', (c: any) => {
        const session = state.checkoutSessions[c.req.param('id')];
        if (!session) return c.html(page('Checkout not found', ''), 404);
        if (session.status !== 'open')
          return c.html(page(`This Checkout is ${session.status}`, ''), 410);
        const price = state.prices[session.pumpkit_line_item.price];
        const product = state.products[price.product];
        const amount = `${(price.unit_amount / 100).toFixed(2)} ${price.currency.toUpperCase()}`;
        const trial = session.pumpkit_trial_days
          ? `<p>${session.pumpkit_trial_days} days free.</p>`
          : '';
        return c.html(
          page(
            `Pay for ${product?.name ?? price.lookup_key}`,
            `<p>${escapeHtml(amount)}${price.recurring ? ` per ${price.recurring.interval}` : ''}</p>${trial}
<form method="post" action="/checkout/${session.id}/pay"><button type="submit">Pay</button></form>
<p><a href="${escapeHtml(session.cancel_url)}">Cancel</a></p>`,
          ),
        );
      });

      // A hosted page waits for its webhooks, so the backend knows the outcome when the browser lands.
      app.post('/checkout/:id/pay', async (c: any) => {
        const session = state.checkoutSessions[c.req.param('id')];
        if (!session || session.status !== 'open')
          return c.html(page('This Checkout is closed', ''), 410);
        const { price: priceId, quantity } = session.pumpkit_line_item;
        const price = state.prices[priceId];
        session.status = 'complete';
        if (session.mode === 'subscription') {
          const subscription = newSubscription(
            session.customer,
            price,
            quantity,
            session.pumpkit_trial_days,
          );
          state.subscriptions[subscription.id] = subscription;
          session.subscription = subscription.id;
          session.payment_status =
            subscription.status === 'trialing' ? 'no_payment_required' : 'paid';
          await send('customer.subscription.created', subscription);
        } else {
          const charge = {
            id: newId('ch'),
            object: 'charge',
            customer: session.customer,
            amount: price.unit_amount * quantity,
            amount_refunded: 0,
            currency: price.currency,
            disputed: false,
            created: now(),
          };
          const intent = {
            id: newId('pi'),
            object: 'payment_intent',
            customer: session.customer,
            status: 'succeeded',
            latest_charge: charge.id,
          };
          charge.payment_intent = intent.id;
          state.charges[charge.id] = charge;
          state.paymentIntents[intent.id] = intent;
          session.payment_intent = intent.id;
          session.payment_status = 'paid';
        }
        await send('checkout.session.completed', session);
        return c.redirect(session.success_url.replace('{CHECKOUT_SESSION_ID}', session.id), 303);
      });

      app.get('/v1/charges/:id', (c: any) => {
        const charge = state.charges[c.req.param('id')];
        return charge ? c.json(charge) : notFound(c, 'charge', c.req.param('id'));
      });

      app.get('/v1/subscriptions', (c: any) => {
        const { customer, status } = queryParams(c);
        const subscriptions = Object.values(state.subscriptions).filter(
          (s) =>
            (!customer || s.customer === customer) &&
            (status === 'all' || (status ? s.status === status : s.status !== 'canceled')),
        );
        return c.json(list('/v1/subscriptions', subscriptions));
      });

      app.delete('/v1/subscriptions/:id', (c: any) => {
        const subscription = state.subscriptions[c.req.param('id')];
        if (!subscription) return notFound(c, 'subscription', c.req.param('id'));
        subscription.status = 'canceled';
        subscription.canceled_at = subscription.ended_at = now();
        sendLater('customer.subscription.deleted', subscription);
        return c.json(subscription);
      });

      // Pumpkit updates a subscription only to end its Trial now; the first charge always succeeds here.
      app.post('/v1/subscriptions/:id', async (c: any) => {
        const subscription = state.subscriptions[c.req.param('id')];
        if (!subscription) return notFound(c, 'subscription', c.req.param('id'));
        const { trial_end: trialEnd, expand = [] } = await bodyParams(c);
        if (trialEnd === 'now') {
          const start = now();
          const [item] = subscription.items.data;
          Object.assign(subscription, {
            status: 'active',
            trial_end: start,
            billing_cycle_anchor: start,
          });
          Object.assign(item, {
            current_period_start: start,
            current_period_end: periodEnd(start, item.price),
          });
          const invoice = {
            id: newId('in'),
            object: 'invoice',
            status: 'paid',
            hosted_invoice_url: null,
          };
          state.invoices[invoice.id] = invoice;
          subscription.latest_invoice = invoice.id;
        }
        sendLater('customer.subscription.updated', subscription);
        const invoice = state.invoices[subscription.latest_invoice];
        return c.json(
          expand.includes('latest_invoice') && invoice
            ? { ...subscription, latest_invoice: invoice }
            : subscription,
        );
      });

      // Every first charge succeeds, so no invoice ever waits on a payment.
      app.get('/v1/invoice_payments', (c: any) => c.json(list('/v1/invoice_payments', [])));

      app.post('/v1/billing_portal/sessions', async (c: any) => {
        const params = await bodyParams(c);
        if (!state.customers[params.customer]) return notFound(c, 'customer', params.customer);
        const portal = {
          id: newId('bps'),
          object: 'billing_portal.session',
          customer: params.customer,
          return_url: params.return_url,
          created: now(),
          livemode: false,
        };
        portal.url = `${baseUrl}/billing_portal/${portal.id}`;
        state.portalSessions[portal.id] = portal;
        return c.json(portal);
      });

      app.get('/billing_portal/:id', (c: any) => {
        const portal = state.portalSessions[c.req.param('id')];
        if (!portal) return c.html(page('Portal session not found', ''), 404);
        const running = Object.values(state.subscriptions).filter(
          (s) => s.customer === portal.customer && s.status !== 'canceled' && !s.cancel_at,
        );
        const forms = running
          .map(
            (s) => `<form method="post" action="/billing_portal/${portal.id}/cancel/${s.id}">
<button type="submit">Cancel ${escapeHtml(s.items.data[0].price.lookup_key ?? s.id)}</button></form>`,
          )
          .join('');
        return c.html(
          page(
            'Manage your subscription',
            `${forms}<p><a href="${escapeHtml(portal.return_url)}">Return</a></p>`,
          ),
        );
      });

      app.post('/billing_portal/:id/cancel/:subscription', async (c: any) => {
        const portal = state.portalSessions[c.req.param('id')];
        const subscription = state.subscriptions[c.req.param('subscription')];
        if (!portal || subscription?.customer !== portal.customer)
          return c.html(page('Not found', ''), 404);
        subscription.cancel_at = subscription.items.data[0].current_period_end;
        await send('customer.subscription.updated', subscription);
        return c.redirect(`/billing_portal/${portal.id}`, 303);
      });
    },
  };
}
