export function toSlug(name: string): string {
  const slug = name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
  return slug || 'app';
}

/** Display name of the app. Set VITE_APP_NAME in frontend/.env. */
export const APP_NAME: string = import.meta.env.VITE_APP_NAME || 'Pumpkit';

/** Prefix for browser storage keys and Web Lock names. */
export const APP_SLUG: string = toSlug(APP_NAME);
