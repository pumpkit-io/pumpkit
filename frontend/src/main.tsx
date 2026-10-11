import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import '@fontsource-variable/inter/wght.css';
import '@fontsource-variable/google-sans-code/wght.css';
import '@fontsource/geist-mono/400.css';
import '@fontsource/geist-mono/500.css';
import './index.css';
import { startAnalytics } from './lib/analyticsConsent';
import { registerSuperProperties } from './lib/analytics';
import { installRefreshOnUnauthorized } from './lib/session';

startAnalytics();
installRefreshOnUnauthorized();
registerSuperProperties({
  environment: import.meta.env.MODE,
  is_mobile: typeof window !== 'undefined' && window.matchMedia('(max-width: 768px)').matches,
});

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
