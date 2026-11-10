import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fetchInstance } from './instance';

const X_ONLY = {
  app_name: 'Pumpkit',
  sells_plans: false,
  sign_in_methods: ['x'],
  operator: null,
  support_email: null,
  analytics: null,
  x_connection: true,
  mcp_url: null,
};

describe('fetchInstance', () => {
  beforeEach(() => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('offers only X, with no Plans, Operator details, support address, analytics or MCP URL, when the backend is unreachable', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));

    await expect(fetchInstance()).resolves.toEqual(X_ONLY);
  });

  it("asks the API on the page's own origin", async () => {
    const fetchMock = vi.fn().mockResolvedValue(Response.json(X_ONLY));
    vi.stubGlobal('fetch', fetchMock);

    await fetchInstance();

    expect(fetchMock).toHaveBeenCalledWith('/api/v1/instance');
  });

  it('falls back the same way when /instance answers with an error', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('', { status: 502 })));

    await expect(fetchInstance()).resolves.toEqual(X_ONLY);
  });
});
