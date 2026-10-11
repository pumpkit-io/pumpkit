export function toSlug(name: string): string {
  const slug = name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
  return slug || 'app';
}

/** Prefix for browser storage keys and Web Lock names, from the Instance's app name. */
export let APP_SLUG: string = toSlug('Pumpkit');

/** Call before the modules that build keys at import time load, or they keep the default slug. */
export function setAppSlug(appName: string): void {
  APP_SLUG = toSlug(appName);
}
