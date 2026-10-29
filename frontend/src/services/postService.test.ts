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

  it("reads a Version's Format and the Parts of its text", async () => {
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

  it("reads a Post's status and its Scheduled post, with the Version it was copied from", async () => {
    vi.spyOn(apiService, 'get').mockResolvedValue({
      data: {
        id: 'post_01',
        brief: 'ship',
        versions: [VERSION],
        status: 'failed',
        scheduled_post: {
          id: 'scheduled_post_01',
          parts: [{ text: 'the final', live: true, x_post_url: 'https://x.com/i/web/status/1' }],
          state: 'failed',
          publish_at: '2026-10-12T07:00:00Z',
          published_at: null,
          x_post_url: null,
          failed_reason: 'X refused it.',
          source_version_id: 'version_attempt_01',
          community: null,
          share_with_followers: false,
          created_at: '2026-10-10T12:00:00Z',
        },
      },
    } as never);

    const post = await postService.get('post_01');

    expect(apiService.get).toHaveBeenCalledWith('/posts/post_01');
    expect(post.status).toBe('failed');
    expect(post.versions[0].parts).toEqual([{ text: 'the final', charCount: 9, charLimit: 280 }]);
    expect(post.scheduledPost).toEqual({
      id: 'scheduled_post_01',
      parts: [{ text: 'the final', live: true, xPostUrl: 'https://x.com/i/web/status/1' }],
      state: 'failed',
      publishAt: '2026-10-12T07:00:00Z',
      publishedAt: null,
      xPostUrl: null,
      failedReason: 'X refused it.',
      sourceVersionId: 'version_attempt_01',
      community: null,
      shareWithFollowers: false,
      createdAt: '2026-10-10T12:00:00Z',
    });
  });

  it("reads a Post's Text with the Version it came from and whether it was edited", async () => {
    vi.spyOn(apiService, 'get').mockResolvedValue({
      data: {
        id: 'post_01',
        brief: 'ship',
        text: {
          format: 'thread',
          parts: [
            { text: 'one', char_count: 3, char_limit: 280 },
            { text: 'two', char_count: 3, char_limit: 280 },
          ],
          version_number: 2,
          edited: true,
        },
        versions: [VERSION],
        status: 'draft',
        scheduled_post: null,
      },
    } as never);

    const post = await postService.get('post_01');

    expect(post.text).toEqual({
      format: 'thread',
      parts: [
        { text: 'one', charCount: 3, charLimit: 280 },
        { text: 'two', charCount: 3, charLimit: 280 },
      ],
      versionNumber: 2,
      edited: true,
    });
  });

  it('reads a Draft with no Scheduled post', async () => {
    vi.spyOn(apiService, 'get').mockResolvedValue({
      data: {
        id: 'post_01',
        brief: 'ship',
        versions: [VERSION],
        status: 'draft',
        scheduled_post: null,
      },
    } as never);

    const post = await postService.get('post_01');

    expect(post.scheduledPost).toBeNull();
    expect(post.status).toBe('draft');
  });

  it('lists a page of one status with each Scheduled post and the counts', async () => {
    vi.spyOn(apiService, 'get').mockResolvedValue({
      data: {
        data: [
          {
            id: 'post_01',
            brief: 'ship',
            status: 'published',
            parts: ['Out now.'],
            format: 'post',
            version_count: 2,
            latest_version_at: '2026-10-10T12:00:00Z',
            scheduled_post: {
              id: 'scheduled_post_01',
              state: 'published',
              publish_at: '2026-10-11T09:00:00Z',
              published_at: '2026-10-11T09:00:05Z',
              community: null,
              share_with_followers: false,
              failed_reason: null,
              x_post_url: 'https://x.com/i/web/status/1',
            },
          },
        ],
        counts: { draft: 3, scheduled: 0, published: 1, failed: 2 },
        next_offset: 20,
      },
    } as never);

    const page = await postService.list('published', 20);

    expect(apiService.get).toHaveBeenCalledWith('/posts', {
      params: { status: 'published', offset: 20, limit: 20 },
    });
    expect(page).toEqual({
      posts: [
        {
          id: 'post_01',
          brief: 'ship',
          status: 'published',
          parts: ['Out now.'],
          format: 'post',
          versionCount: 2,
          latestVersionAt: '2026-10-10T12:00:00Z',
          scheduledPost: {
            id: 'scheduled_post_01',
            state: 'published',
            publishAt: '2026-10-11T09:00:00Z',
            publishedAt: '2026-10-11T09:00:05Z',
            community: null,
            shareWithFollowers: false,
            failedReason: null,
            xPostUrl: 'https://x.com/i/web/status/1',
          },
        },
      ],
      counts: { draft: 3, scheduled: 0, published: 1, failed: 2 },
      nextOffset: 20,
    });
  });
});
