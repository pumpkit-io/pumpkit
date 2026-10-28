import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const css = readFileSync(path.resolve(__dirname, './index.css'), 'utf8');
const tailwindConfig = readFileSync(path.resolve(__dirname, '../tailwind.config.ts'), 'utf8');

function tokens(selector: string): Map<string, string> {
  const start = css.indexOf(`${selector} {`);
  const body = css.slice(start, css.indexOf('\n  }', start));
  const found = new Map<string, string>();
  for (const match of body.matchAll(/(--[\w-]+):\s*([^;]+);/g)) {
    found.set(match[1], match[2].trim());
  }
  return found;
}

const light = tokens(':root');
const dark = tokens('.dark');

function luminance(hsl: string): number {
  const [h, s, l] = hsl.replace(/%/g, '').split(/\s+/).map(Number);
  const a = (s / 100) * Math.min(l / 100, 1 - l / 100);
  const channel = (n: number) => {
    const k = (n + h / 30) % 12;
    const c = l / 100 - a * Math.max(-1, Math.min(k - 3, 9 - k, 1));
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel(0) + 0.7152 * channel(8) + 0.0722 * channel(4);
}

function contrast(theme: Map<string, string>, text: string, surface: string): number {
  const [hi, lo] = [luminance(theme.get(text)!), luminance(theme.get(surface)!)].sort(
    (x, y) => y - x,
  );
  return (hi + 0.05) / (lo + 0.05);
}

const textPairs: [string, string][] = [
  ['--foreground', '--background'],
  ['--card-foreground', '--card'],
  ['--popover-foreground', '--popover'],
  ['--muted-foreground', '--background'],
  ['--muted-foreground', '--card'],
  ['--muted-foreground', '--muted'],
  ['--primary-foreground', '--primary'],
  ['--primary', '--background'],
  ['--primary', '--card'],
  ['--secondary-foreground', '--secondary'],
  ['--accent-foreground', '--accent'],
  ['--destructive-foreground', '--destructive'],
  ['--destructive', '--card'],
  ['--success', '--card'],
  ['--warning', '--card'],
];

describe('theme tokens', () => {
  it('defines the same colour token names in light and dark mode', () => {
    const colours = (theme: Map<string, string>) =>
      [...theme.keys()].filter((name) => name !== '--radius').sort();
    expect(colours(light)).toEqual(colours(dark));
  });

  it('defines every colour the Tailwind config reads', () => {
    const used = [...tailwindConfig.matchAll(/var\((--[\w-]+)\)/g)]
      .map((match) => match[1])
      .filter((name) => !name.startsWith('--radix-') && name !== '--radius');
    for (const name of new Set(used)) {
      expect(light.has(name), `${name} in :root`).toBe(true);
      expect(dark.has(name), `${name} in .dark`).toBe(true);
    }
  });

  it.each([
    ['light', light],
    ['dark', dark],
  ])('keeps text readable in %s mode', (_mode, theme) => {
    for (const [text, surface] of textPairs) {
      expect(contrast(theme, text, surface), `${text} on ${surface}`).toBeGreaterThanOrEqual(4.5);
    }
  });

  it.each([
    ['light', light],
    ['dark', dark],
  ])('gives input borders 3:1 against their surface in %s mode', (_mode, theme) => {
    expect(contrast(theme, '--input', '--background')).toBeGreaterThanOrEqual(3);
    expect(contrast(theme, '--input', '--card')).toBeGreaterThanOrEqual(3);
  });
});
