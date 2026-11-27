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

  it('titles every preview with the landing headline', () => {
    const titles = [
      head.querySelector('title')?.textContent ?? '',
      meta('property="og:title"'),
      meta('name="twitter:title"'),
    ];
    for (const text of titles) {
      expect(text).toBe('Pumpkit: run your X account on autopilot with AI agents [open-source]');
    }
  });

  it('describes what Pumpkit does, as the landing page does', () => {
    const data = JSON.parse(
      head.querySelector('script[type="application/ld+json"]')?.textContent ?? '',
    );
    const graphDescriptions = (data['@graph'] as { description?: string }[])
      .map((node) => node.description)
      .filter((text) => text !== undefined);
    const descriptions = [
      meta('name="description"'),
      meta('property="og:description"'),
      meta('name="twitter:description"'),
      ...graphDescriptions,
    ];
    expect(descriptions).toHaveLength(5);
    for (const text of descriptions) {
      expect(text).toBe(
        'Pumpkit writes and schedules posts on X for you. Posts sound like you. Use it in the web app, or use the MCP to let your agents run it.',
      );
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

  it('loads nothing from Google Fonts', () => {
    expect(head.innerHTML).not.toMatch(/fonts\.googleapis\.com|fonts\.gstatic\.com/);
  });
});
