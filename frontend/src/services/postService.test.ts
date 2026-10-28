import { afterEach, describe, expect, it, vi } from 'vitest';
import { apiService } from './apiService';
import { postService } from './postService';

const VERSION = {
  id: 'version_attempt_01',
  number: 1,
  feedback: null,
  format: 'post',
  parts: [{ text: 'the final', char_count: 9, char_limit: 280 }],
  tells: [{ name: 'em_dash', description: 'em dash' }],
};

describe('postService', () => {
  afterEach(() => vi.restoreAllMocks());

  it("reads a Version's Format and the Parts of its Final", async () => {
    vi.spyOn(apiService, 'post').mockResolvedValue({
      data: { id: 'post_01', brief: 'ship', versions: [VERSION] },
    } as never);

    const post = await postService.start('ship', 'post');

    expect(apiService.post).toHaveBeenCalledWith('/posts', { brief: 'ship', format: 'post' });
    expect(post.versions).toEqual([
      {
        id: 'version_attempt_01',
        number: 1,
        feedback: null,
        format: 'post',
        parts: [{ text: 'the final', charCount: 9, charLimit: 280 }],
        tells: [{ name: 'em_dash', description: 'em dash' }],
      },
    ]);
  });
});
