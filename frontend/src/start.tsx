import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import { InstanceProvider } from './features/instance/InstanceProvider';
import { registerSuperProperties, startAnalytics } from './lib/analyticsConsent';
import type { Instance } from './lib/instance';
import { installRefreshOnUnauthorized } from './lib/session';

export function start(instance: Instance): void {
  startAnalytics(instance.analytics);
  installRefreshOnUnauthorized();
  registerSuperProperties({
    environment: import.meta.env.MODE,
    is_mobile: typeof window !== 'undefined' && window.matchMedia('(max-width: 768px)').matches,
  });

  ReactDOM.createRoot(document.getElementById('root')!).render(
    <React.StrictMode>
      <InstanceProvider instance={instance}>
        <App />
      </InstanceProvider>
    </React.StrictMode>,
  );
}
