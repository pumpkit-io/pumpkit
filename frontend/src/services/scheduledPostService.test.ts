import { afterEach, describe, expect, it, vi } from 'vitest';
import { apiService } from './apiService';
import { scheduledPostService } from './scheduledPostService';

const COMMUNITY = { id: '1493446837214187523', name: 'Build in Public' };
const SCHEDULED = {
  id: 'scheduled_post_1',
  text: 'The final.',
  state: 'scheduled',
  publish_at: '2026-10-12T07:00:00Z',
  published_at: null,
  x_post_url: null,
  failed_reason: null,
  community: null,
  share_with_followers: false,
  created_at: '2026-10-10T12:00:00Z',
};

describe('scheduledPostService', () => {
  afterEach(() => vi.restoreAllMocks());

  it('sends a Final as its Version alone, for the server to copy', async () => {
    const post = vi.spyOn(apiService, 'post').mockResolvedValue({ data: SCHEDULED } as never);

    await scheduledPostService.schedule(
      { sourceVersionId: 'version_attempt_01' },
      '2026-10-12T07:00:00.000Z',
      { community: null, shareWithFollowers: false },
    );

    expect(post).toHaveBeenCalledWith('/scheduled-posts', {
      source_version_id: 'version_attempt_01',
      publish_at: '2026-10-12T07:00:00.000Z',
      community: null,
      share_with_followers: false,
    });
  });

  it('sends a Community as its ID, for the server to look up its name', async () => {
    const post = vi.spyOn(apiService, 'post').mockResolvedValue({ data: SCHEDULED } as never);
    const patch = vi.spyOn(apiService, 'patch').mockResolvedValue({ data: SCHEDULED } as never);

    await scheduledPostService.postNow(
      { text: 'Hello Community.' },
      { community: COMMUNITY, shareWithFollowers: true },
    );
    await scheduledPostService.edit('scheduled_post_1', { community: COMMUNITY });
    await scheduledPostService.edit('scheduled_post_1', { community: null });

    expect(post).toHaveBeenCalledWith('/scheduled-posts', {
      text: 'Hello Community.',
      publish_now: true,
      community: COMMUNITY.id,
      share_with_followers: true,
    });
    expect(patch.mock.calls.map(([, body]) => (body as { community: unknown }).community)).toEqual([
      COMMUNITY.id,
      null,
    ]);
  });
});
