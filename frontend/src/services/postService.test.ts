import { afterEach, describe, expect, it, vi } from 'vitest';
import { apiService } from './apiService';
import { postService } from './postService';

const VERSION = {
  id: 'version_attempt_01',
  number: 1,
  feedback: null,
  format: 'post',
  parts: [{ text: 'the final', char_count: 9, char_limit: 280 }],
  created_at: '2026-10-10T12:00:30Z',
};

describe('postService', () => {
  afterEach(() => vi.restoreAllMocks());

  it("reads a version's Format and the Parts of its text", async () => {
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
        createdAt: '2026-10-10T12:00:30Z',
      },
    ]);
  });

  it("reads a Post's Text, its status and its Scheduled post", async () => {
    vi.spyOn(apiService, 'get').mockResolvedValue({
      data: {
        id: 'post_01',
        brief: 'ship',
        text: {
          format: 'post',
          parts: [{ text: 'the final', char_count: 9, char_limit: 280, media: [] }],
          version_number: 1,
          edited: false,
        },
        versions: [VERSION],
        status: 'failed',
        scheduled_post: {
          id: 'scheduled_post_01',
          parts: [
            {
              text: 'the final',
              live: true,
              x_post_url: 'https://x.com/i/web/status/1',
              media: [],
            },
          ],
          state: 'failed',
          publish_at: '2026-10-12T07:00:00Z',
          published_at: null,
          x_post_url: null,
          failed_reason: 'X refused it.',
          community: null,
          share_with_followers: false,
          created_at: '2026-10-10T12:00:00Z',
          posting: false,
        },
      },
    } as never);

    const post = await postService.get('post_01');

    expect(apiService.get).toHaveBeenCalledWith('/posts/post_01');
    expect(post.text).toEqual({
      format: 'post',
      parts: [{ text: 'the final', charCount: 9, charLimit: 280 }],
      versionNumber: 1,
      edited: false,
    });
    expect(post.status).toBe('failed');
    expect(post.versions[0].parts).toEqual([{ text: 'the final', charCount: 9, charLimit: 280 }]);
    expect(post.scheduledPost).toEqual({
      id: 'scheduled_post_01',
      parts: [
        { text: 'the final', live: true, xPostUrl: 'https://x.com/i/web/status/1', media: [] },
      ],
      state: 'failed',
      publishAt: '2026-10-12T07:00:00Z',
      publishedAt: null,
      xPostUrl: null,
      failedReason: 'X refused it.',
      community: null,
      shareWithFollowers: false,
      createdAt: '2026-10-10T12:00:00Z',
      posting: false,
    });
  });

  it("reads a Post's Plan, and none on a Post written before Briefs were planned", async () => {
    const read = { id: 'post_01', brief: 'ship', text: null, versions: [], status: 'draft' };
    const get = vi.spyOn(apiService, 'get');
    get.mockResolvedValueOnce({
      data: {
        ...read,
        scheduled_post: null,
        plan: {
          core_idea: 'Shipping small things beats planning big ones.',
          takeaway: 'Ship the smallest thing that works this week.',
          funnel: 'middle',
          desired_action: 'bookmark',
          format: 'post',
          length: 'medium',
          structure: 'hook_problem_insight_closer',
        },
      },
    } as never);
    get.mockResolvedValueOnce({
      data: { ...read, scheduled_post: null, plan: null },
    } as never);

    expect((await postService.get('post_01')).plan).toEqual({
      coreIdea: 'Shipping small things beats planning big ones.',
      takeaway: 'Ship the smallest thing that works this week.',
      funnel: 'middle',
      desiredAction: 'bookmark',
      format: 'post',
      length: 'medium',
      structure: 'hook_problem_insight_closer',
    });
    expect((await postService.get('post_01')).plan).toBeNull();
  });

  it("reads a Post's Text with the Version it came from and whether it was edited, and its Media", async () => {
    vi.spyOn(apiService, 'get').mockResolvedValue({
      data: {
        id: 'post_01',
        brief: 'ship',
        text: {
          format: 'thread',
          parts: [
            { text: 'one', char_count: 3, char_limit: 280, media: [] },
            {
              text: 'two',
              char_count: 3,
              char_limit: 280,
              media: [
                {
                  id: 'media_01',
                  kind: 'image',
                  preview_url: '/media/media_01/preview',
                  width: 40,
                  height: 30,
                  alt_text: 'A rising line.',
                },
              ],
            },
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
    expect(post.textMedia).toEqual([
      [],
      [
        {
          id: 'media_01',
          kind: 'image',
          previewUrl: '/media/media_01/preview',
          width: 40,
          height: 30,
          altText: 'A rising line.',
        },
      ],
    ]);
  });

  it('reads a Draft with no Scheduled post', async () => {
    vi.spyOn(apiService, 'get').mockResolvedValue({
      data: {
        id: 'post_01',
        brief: 'ship',
        text: null,
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
              posting: false,
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
            posting: false,
          },
        },
      ],
      counts: { draft: 3, scheduled: 0, published: 1, failed: 2 },
      nextOffset: 20,
    });
  });

  it('restores a Version by its number and reads back the Text', async () => {
    vi.spyOn(apiService, 'post').mockResolvedValue({
      data: {
        format: 'post',
        parts: [{ text: 'the first', char_count: 9, char_limit: 280 }],
        version_number: 1,
        edited: false,
      },
    } as never);

    const text = await postService.restoreVersion('post_01', 1);

    expect(apiService.post).toHaveBeenCalledWith('/posts/post_01/versions/1/restore');
    expect(text).toEqual({
      format: 'post',
      parts: [{ text: 'the first', charCount: 9, charLimit: 280 }],
      versionNumber: 1,
      edited: false,
    });
  });

  it('saves the Text with whether it ends with a first reply, and reads it back', async () => {
    vi.spyOn(apiService, 'put').mockResolvedValue({
      data: {
        format: 'post',
        parts: [
          { text: 'the post', char_count: 8, char_limit: 280, media: [] },
          { text: 'Try it: x.co', char_count: 12, char_limit: 280, media: [] },
        ],
        first_reply: true,
        version_number: 1,
        edited: true,
      },
    } as never);

    const text = await postService.saveText('post_01', ['the post', 'Try it: x.co'], true);

    expect(apiService.put).toHaveBeenCalledWith('/posts/post_01/text', {
      parts: ['the post', 'Try it: x.co'],
      first_reply: true,
    });
    expect(text.firstReply).toBe(true);
    expect(text.format).toBe('post');
  });
});
