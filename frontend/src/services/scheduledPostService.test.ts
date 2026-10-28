import { afterEach, describe, expect, it, vi } from 'vitest';
import { apiService } from './apiService';
import { scheduledPostService } from './scheduledPostService';

const COMMUNITY = { id: '1493446837214187523', name: 'Build in Public' };
const SCHEDULED = {
  id: 'scheduled_post_1',
  parts: [{ text: 'The final.', live: false, x_post_url: null }],
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
      { sourceVersionId: 'version_attempt_01' },
      { community: COMMUNITY, shareWithFollowers: true },
    );
    await scheduledPostService.edit('scheduled_post_1', { community: COMMUNITY });
    await scheduledPostService.edit('scheduled_post_1', { community: null });

    expect(post).toHaveBeenCalledWith('/scheduled-posts', {
      source_version_id: 'version_attempt_01',
      publish_now: true,
      community: COMMUNITY.id,
      share_with_followers: true,
    });
    expect(patch.mock.calls.map(([, body]) => (body as { community: unknown }).community)).toEqual([
      COMMUNITY.id,
      null,
    ]);
  });

  it('retries one with a Version, now or at a time', async () => {
    const patch = vi.spyOn(apiService, 'patch').mockResolvedValue({ data: SCHEDULED } as never);

    await scheduledPostService.edit('scheduled_post_1', {
      sourceVersionId: 'version_attempt_02',
      publishNow: true,
    });
    await scheduledPostService.edit('scheduled_post_1', {
      publishAt: '2026-10-12T07:00:00.000Z',
    });

    expect(patch.mock.calls.map(([, body]) => body)).toEqual([
      { source_version_id: 'version_attempt_02', publish_now: true },
      { publish_at: '2026-10-12T07:00:00.000Z' },
    ]);
  });

  it('reads back each Part in order with whether it is live', async () => {
    const link = 'https://x.com/i/web/status/1890000000000000001';
    vi.spyOn(apiService, 'post').mockResolvedValue({
      data: {
        ...SCHEDULED,
        parts: [
          { text: 'First.', live: true, x_post_url: link },
          { text: 'Second.', live: false, x_post_url: null },
        ],
      },
    } as never);

    const scheduled = await scheduledPostService.schedule(
      { sourceVersionId: 'version_attempt_01' },
      '2026-10-12T07:00:00.000Z',
      { community: null, shareWithFollowers: false },
    );

    expect(scheduled.parts).toEqual([
      { text: 'First.', live: true, xPostUrl: link },
      { text: 'Second.', live: false, xPostUrl: null },
    ]);
  });
});
