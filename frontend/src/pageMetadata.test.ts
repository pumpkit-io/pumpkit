import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const html = readFileSync(path.resolve(__dirname, '../index.html'), 'utf8');
const head = new DOMParser().parseFromString(html, 'text/html').head;

function meta(selector: string): string {
  return head.querySelector<HTMLMetaElement>(`meta[${selector}]`)?.content ?? '';
}

describe('page metadata in index.html', () => {
  it('does not describe the old reply tool', () => {
    const text = head.innerHTML;
    expect(text).not.toMatch(/telegram/i);
    expect(text).not.toMatch(/social listening/i);
    expect(text).not.toMatch(/\brepl(y|ies)\b/i);
  });

  it('describes Pumpkit as an open-source writing tool for X', () => {
    const descriptions = [
      head.querySelector('title')?.textContent ?? '',
      meta('name="description"'),
      meta('property="og:title"'),
      meta('property="og:description"'),
      meta('name="twitter:title"'),
      meta('name="twitter:description"'),
    ];
    for (const text of descriptions) {
      expect(text).toMatch(/open-source writing tool for X/i);
    }
  });

  it('carries a JSON-LD graph with Organization, WebSite and SoftwareApplication', () => {
    const script = head.querySelector('script[type="application/ld+json"]');
    expect(script).not.toBeNull();
    const data = JSON.parse(script?.textContent ?? '');
    expect(data['@context']).toBe('https://schema.org');
    const types = (data['@graph'] as { '@type': string }[]).map((node) => node['@type']);
    expect(types).toEqual(
      expect.arrayContaining(['Organization', 'WebSite', 'SoftwareApplication']),
    );
  });

  it('loads Inter at weights 300 to 700 and Google Sans Code for the wordmark', () => {
    const href =
      head.querySelector<HTMLLinkElement>('link[rel="stylesheet"][href*="fonts.googleapis.com"]')
        ?.href ?? '';
    const families = new URL(href).searchParams.getAll('family');
    expect(families).toContain('Inter:wght@300..700');
    expect(families.some((family) => family.startsWith('Google Sans Code'))).toBe(true);
  });
});
