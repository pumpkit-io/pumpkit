// X serves each profile photo in fixed sizes, named by a suffix before the extension.
const X_SIZES: [suffix: string, px: number][] = [
  ['normal', 48],
  ['bigger', 73],
  ['200x200', 200],
  ['400x400', 400],
];
const SIZE_SUFFIX = /_(?:mini|normal|bigger|200x200|400x400)(\.[A-Za-z0-9]+)?$/;

/**
 * X's URL for the smallest variant of a photo that stays sharp at `px` CSS pixels on a 2x
 * screen. A URL without X's size suffix comes back unchanged.
 */
export function xPhotoAt(url: string | null, px: number): string | null {
  if (!url || !SIZE_SUFFIX.test(url)) return url;
  const [suffix] = X_SIZES.find(([, size]) => size >= px * 2) ?? X_SIZES[X_SIZES.length - 1];
  return url.replace(SIZE_SUFFIX, `_${suffix}$1`);
}
