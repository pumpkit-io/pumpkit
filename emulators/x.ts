import { createHash, randomBytes } from 'node:crypto';

interface Account {
  id: string;
  username: string;
  name: string;
  confirmed_email?: string;
  description?: string;
  location?: string;
  url?: string;
}

interface Grant {
  id: string;
  userId: string;
  scope: string;
}

interface Authorization extends Grant {
  challenge: string;
  redirectUri: string;
  expiresAt: number;
}

interface State {
  users: Record<string, Account>;
  codes: Record<string, Authorization>;
  access: Record<string, Grant>;
  refresh: Record<string, Grant>;
  events: { kind: string; userId: string }[];
}

const emptyState = (): State => ({ users: {}, codes: {}, access: {}, refresh: {}, events: [] });
const escapeHtml = (value: string) =>
  value.replace(
    /[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]!,
  );
const token = () => randomBytes(24).toString('base64url');
const avatar = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aGDcAAAAASUVORK5CYII=',
  'base64',
);

export function pumpkitX(config: {
  clientId: string;
  clientSecret: string;
  redirectUris: string[];
  apiUrl: string;
}) {
  return {
    kind: 'emulate.http',
    apiVersion: 1,
    name: 'pumpkit-x',
    state: emptyState,
    validateSeed(value: any): State {
      if (value?.codes) return value as State;
      const state = emptyState();
      for (const user of value?.users ?? []) state.users[user.id] = user;
      return state;
    },
    setup({ app, state }: { app: any; state: State }) {
      const valid = (p: URLSearchParams) =>
        p.get('client_id') === config.clientId &&
        config.redirectUris.includes(p.get('redirect_uri') ?? '') &&
        p.get('response_type') === 'code' &&
        p.get('code_challenge_method') === 'S256' &&
        /^[A-Za-z0-9_-]{43}$/.test(p.get('code_challenge') ?? '') &&
        Boolean(p.get('state')) &&
        Boolean(p.get('scope'));
      const basic = `Basic ${Buffer.from(`${config.clientId}:${config.clientSecret}`).toString('base64')}`;
      const issue = (grant: Grant) => {
        const access = token(),
          refresh = token();
        state.access[access] = grant;
        state.refresh[refresh] = grant;
        return {
          access_token: access,
          refresh_token: refresh,
          token_type: 'bearer',
          expires_in: 7200,
          scope: grant.scope,
        };
      };
      app.get('/i/oauth2/authorize', (c: any) => {
        const p = new URL(c.req.url).searchParams;
        if (!valid(p)) return c.json({ error: 'invalid_request' }, 400);
        const hidden = [...p]
          .map(
            ([key, value]) =>
              `<input type="hidden" name="${escapeHtml(key)}" value="${escapeHtml(value)}">`,
          )
          .join('');
        const users = Object.values(state.users)
          .map(
            (user) =>
              `<p><button name="user_id" value="${escapeHtml(user.id)}">${escapeHtml(user.name)} (${escapeHtml(user.confirmed_email ?? 'no confirmed email')})</button></p>`,
          )
          .join('');
        return c.html(
          `<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Local X authorization</title><h1>Authorize local X account</h1><form method="post">${hidden}${users}<button name="user_id" value="cancel">Cancel</button></form></html>`,
        );
      });
      app.post('/i/oauth2/authorize', async (c: any) => {
        const p = new URLSearchParams(await c.req.text());
        if (!valid(p)) return c.json({ error: 'invalid_request' }, 400);
        const redirect = new URL(p.get('redirect_uri')!);
        redirect.searchParams.set('state', p.get('state')!);
        const userId = p.get('user_id')!;
        if (userId === 'cancel') redirect.searchParams.set('error', 'access_denied');
        else {
          if (!state.users[userId]) return c.json({ error: 'invalid_request' }, 400);
          const code = token();
          state.codes[code] = {
            id: token(),
            userId,
            scope: p.get('scope')!,
            challenge: p.get('code_challenge')!,
            redirectUri: p.get('redirect_uri')!,
            expiresAt: Date.now() + 600_000,
          };
          state.events.push({ kind: 'authorize', userId });
          redirect.searchParams.set('code', code);
        }
        return c.redirect(redirect.toString(), 303);
      });
      app.post('/2/oauth2/token', async (c: any) => {
        if (c.req.header('Authorization') !== basic)
          return c.json({ error: 'invalid_client' }, 401);
        const p = new URLSearchParams(await c.req.text());
        if (p.get('grant_type') === 'refresh_token') {
          const previous = p.get('refresh_token') ?? '',
            grant = state.refresh[previous];
          delete state.refresh[previous];
          if (!grant) return c.json({ error: 'invalid_grant' }, 400);
          state.events.push({ kind: 'refresh', userId: grant.userId });
          return c.json(issue(grant));
        }
        const code = p.get('code') ?? '',
          authorization = state.codes[code];
        delete state.codes[code];
        const challenge = createHash('sha256')
          .update(p.get('code_verifier') ?? '')
          .digest('base64url');
        if (
          p.get('grant_type') !== 'authorization_code' ||
          !authorization ||
          authorization.expiresAt <= Date.now() ||
          authorization.challenge !== challenge ||
          authorization.redirectUri !== p.get('redirect_uri')
        ) {
          return c.json({ error: 'invalid_grant' }, 400);
        }
        state.events.push({ kind: 'token', userId: authorization.userId });
        return c.json(
          issue({ id: authorization.id, userId: authorization.userId, scope: authorization.scope }),
        );
      });
      app.get('/2/users/me', (c: any) => {
        const grant = state.access[(c.req.header('Authorization') ?? '').replace(/^Bearer /, '')];
        if (!grant) return c.json({ error: 'invalid_token' }, 401);
        const user = state.users[grant.userId];
        const fields = new URL(c.req.url).searchParams.get('user.fields')?.split(',') ?? [];
        const data: Record<string, unknown> = { id: user.id, username: user.username };
        if (fields.includes('name')) data.name = user.name;
        if (
          fields.includes('confirmed_email') &&
          grant.scope.split(' ').includes('users.email') &&
          user.confirmed_email
        )
          data.confirmed_email = user.confirmed_email;
        if (fields.includes('profile_image_url'))
          data.profile_image_url = `${config.apiUrl}/_pumpkit/avatar.png`;
        if (fields.includes('subscription_type')) data.subscription_type = 'None';
        for (const field of ['description', 'location', 'url'] as const)
          if (fields.includes(field) && user[field]) data[field] = user[field];
        state.events.push({ kind: 'profile', userId: user.id });
        return c.json({ data });
      });
      app.post('/2/oauth2/revoke', async (c: any) => {
        if (c.req.header('Authorization') !== basic)
          return c.json({ error: 'invalid_client' }, 401);
        const p = new URLSearchParams(await c.req.text()),
          value = p.get('token') ?? '';
        const grant = state.refresh[value];
        if (grant) {
          for (const [credential, active] of Object.entries(state.access)) {
            if (active.id === grant.id) delete state.access[credential];
          }
          for (const [credential, active] of Object.entries(state.refresh)) {
            if (active.id === grant.id) delete state.refresh[credential];
          }
        } else delete state.access[value];
        return c.json({ revoked: true });
      });
      app.get('/_pumpkit/events', (c: any) => c.json(state.events));
      app.get('/_pumpkit/avatar.png', (c: any) =>
        c.body(avatar, 200, { 'Content-Type': 'image/png' }),
      );
      // All unsupported writes fail locally, including direct Post now calls while the worker is disabled.
      for (const path of [
        '/2/tweets',
        '/2/media/upload/initialize',
        '/2/media/upload/:id/append',
        '/2/media/upload/:id/finalize',
        '/2/media/metadata',
      ]) {
        app.post(path, (c: any) =>
          c.json({ detail: 'Publishing is disabled in the local X stand-in.' }, 403),
        );
      }
    },
  };
}
