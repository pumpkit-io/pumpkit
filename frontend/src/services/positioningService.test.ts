import { afterEach, describe, expect, it, vi } from 'vitest';
import { apiService } from './apiService';
import { positioningService } from './positioningService';

describe('positioningService', () => {
  afterEach(() => vi.restoreAllMocks());

  it('reads the Positioning and whether a draft can be asked for', async () => {
    const get = vi.spyOn(apiService, 'get').mockResolvedValue({
      data: { text: 'I post about pricing.', saved_at: '2026-10-10T12:00:30Z', can_draft: false },
    } as never);

    expect(await positioningService.get()).toEqual({
      text: 'I post about pricing.',
      canDraft: false,
    });
    expect(get).toHaveBeenCalledWith('/positioning');
  });

  it('asks for a draft and returns its text', async () => {
    const post = vi.spyOn(apiService, 'post').mockResolvedValue({
      data: { text: 'I post about pricing.', reason: null, can_draft: true },
    } as never);

    expect(await positioningService.draft()).toEqual({
      text: 'I post about pricing.',
      reason: null,
      canDraft: true,
    });
    expect(post).toHaveBeenCalledWith('/positioning/draft');
  });

  it('returns why no draft could be made', async () => {
    vi.spyOn(apiService, 'post').mockResolvedValue({
      data: { text: null, reason: "We couldn't read your X profile.", can_draft: false },
    } as never);

    expect(await positioningService.draft()).toEqual({
      text: null,
      reason: "We couldn't read your X profile.",
      canDraft: false,
    });
  });
});
