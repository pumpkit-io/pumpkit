import React from 'react';
import ReactDOM from 'react-dom/client';
import { PostHogProvider } from 'posthog-js/react';
import App from './App';
import './index.css';
import { initPostHog, posthog } from './lib/posthog';
import { registerSuperProperties } from './lib/analytics';
import { installRefreshOnUnauthorized } from './lib/session';

initPostHog();
installRefreshOnUnauthorized();
registerSuperProperties({
  environment: import.meta.env.MODE,
  is_mobile: typeof window !== 'undefined' && window.matchMedia('(max-width: 768px)').matches,
});

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <PostHogProvider client={posthog}>
      <App />
    </PostHogProvider>
  </React.StrictMode>,
);
