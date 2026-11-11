import type { Plugin } from 'vite';
import { createXCallbackRelay } from './localXCallbackRelay';

export function localXCallbackRelay(env: NodeJS.ProcessEnv): Plugin {
  return {
    name: 'local-x-callback-relay',
    apply: 'serve',
    configureServer(server) {
      if (env.X_LOCAL_CALLBACK_RELAY !== 'true') return;
      if (env.ENV !== 'local') throw new Error('X callback relay requires ENV=local');
      server.middlewares.use(createXCallbackRelay(env.DEV_PUBLIC_URL ?? ''));
    },
  };
}
