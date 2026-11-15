import { afterEach, describe, expect, it, vi } from 'vitest';
import { apiService } from './apiService';
import { positioningService } from './positioningService';

describe('positioningService', () => {
  afterEach(() => vi.restoreAllMocks());

  it('reads the Positioning, with no draft once one is saved', async () => {
    const get = vi.spyOn(apiService, 'get').mockResolvedValue({
      data: { text: 'I post about pricing.', saved_at: '2026-10-10T12:00:30Z', draft: null },
    } as never);

    expect(await positioningService.get()).toEqual({ text: 'I post about pricing.', draft: null });
    expect(get).toHaveBeenCalledWith('/positioning');
  });

  it('reads the Positioning draft of a User with no Positioning', async () => {
    vi.spyOn(apiService, 'get').mockResolvedValue({
      data: {
        text: null,
        saved_at: null,
        draft: { state: 'failed', text: null, reason: "We couldn't read your X profile." },
      },
    } as never);

    expect(await positioningService.get()).toEqual({
      text: null,
      draft: { state: 'failed', text: null, reason: "We couldn't read your X profile." },
    });
  });

  it('starts a draft without waiting for it', async () => {
    const post = vi.spyOn(apiService, 'post').mockResolvedValue({ data: '' } as never);

    await positioningService.startDraft();

    expect(post).toHaveBeenCalledWith('/positioning/draft/start');
  });
});
