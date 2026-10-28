import '@fontsource-variable/inter/wght.css';
import '@fontsource/geist-mono/400.css';
import '@fontsource/geist-mono/500.css';
import './index.css';
import { setAppSlug } from './lib/app';
import { fetchInstance } from './lib/instance';

// The rest of the app loads only after the slug is set: several modules build storage keys at import.
void fetchInstance().then(async (instance) => {
  setAppSlug(instance.app_name);
  const { start } = await import('./start');
  start(instance);
});
