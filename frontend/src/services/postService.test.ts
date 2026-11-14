import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { apiService } from './apiService';
import {
  isUnwritten,
  postService,
  type Plan,
  type PostDetail,
  type UnwrittenPost,
  VersionNotWritten,
  WRITING_POLL_MS,
} from './postService';

const PLAN = {
  core_idea: 'Ship small.',
  takeaway: 'Ship this week.',
  funnel: 'middle',
  desired_action: 'bookmark',
  format: 'post',
  length: 'short',
  structure: 'few_lines',
};
const SHOWN_PLAN: Plan = {
  coreIdea: 'Ship small.',
  takeaway: 'Ship this week.',
  funnel: 'middle',
  desiredAction: 'bookmark',
  format: 'post',
  length: 'short',
  structure: 'few_lines',
};

/** The Post `get` read, which the test expects written. */
function written(post: PostDetail | UnwrittenPost): PostDetail {
  if (isUnwritten(post)) throw new Error('Expected a written post.');
  return post;
}

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

  it('starts a Post and reads it as being written, with its Plan', async () => {
    vi.spyOn(apiService, 'post').mockResolvedValue({
      data: { id: 'post_01', brief: 'ship', plan: PLAN, versions: [], writing_state: 'writing' },
    } as never);

    const post = await postService.start('ship');

    expect(apiService.post).toHaveBeenCalledWith('/posts', { brief: 'ship' });
    expect(post).toEqual<UnwrittenPost>({
      id: 'post_01',
      brief: 'ship',
      plan: SHOWN_PLAN,
      writingState: 'writing',
    });
  });

  it('retries the first Version of a Post Pumpkit could not write', async () => {
    vi.spyOn(apiService, 'post').mockResolvedValue({
      data: { id: 'post_01', brief: 'ship', plan: PLAN, versions: [], writing_state: 'writing' },
    } as never);

    const post = await postService.retry('post_01');

    expect(apiService.post).toHaveBeenCalledWith('/posts/post_01/retry');
    expect(post.writingState).toBe('writing');
  });

  it.each(['writing', 'not_written'] as const)(
    'reads a Post with no status as unwritten, %s',
    async (writingState) => {
      vi.spyOn(apiService, 'get').mockResolvedValue({
        data: {
          id: 'post_01',
          brief: 'ship',
          plan: PLAN,
          text: null,
          versions: [],
          writing_state: writingState,
          status: null,
          scheduled_post: null,
        },
      } as never);

      const post = await postService.get('post_01');

      expect(post).toEqual<UnwrittenPost>({
        id: 'post_01',
        brief: 'ship',
        plan: SHOWN_PLAN,
        writingState,
      });
    },
  );

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

    const post = written(await postService.get('post_01'));

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

    const post = written(await postService.get('post_01'));

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

    const post = written(await postService.get('post_01'));

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
  describe('Feedback, written in the background', () => {
    const VERSION_TWO = {
      ...VERSION,
      id: 'version_attempt_02',
      number: 2,
      feedback: 'shorter',
      parts: [{ text: 'shorter', char_count: 7, char_limit: 280 }],
    };

    /** The Post as `GET /posts/{id}` answers it, with `versions` and its writing state. */
    function read(versions: object[], writingState: 'writing' | null) {
      const latest = versions[versions.length - 1] as typeof VERSION;
      return {
        data: {
          id: 'post_01',
          brief: 'ship',
          plan: PLAN,
          text: {
            format: 'post',
            first_reply: false,
            parts: latest.parts.map((p) => ({ ...p, media: [] })),
            version_number: latest.number,
            edited: false,
          },
          versions,
          writing_state: writingState,
          status: 'draft',
          scheduled_post: null,
        },
      };
    }

    beforeEach(() => {
      vi.useFakeTimers();
      vi.spyOn(apiService, 'post').mockResolvedValue(read([VERSION], 'writing') as never);
    });
    afterEach(() => vi.useRealTimers());

    it('reads a Post that Feedback is rewriting as writing', async () => {
      vi.spyOn(apiService, 'get').mockResolvedValue(read([VERSION], 'writing') as never);

      const post = written(await postService.get('post_01'));

      expect(post.writing).toBe(true);
    });

    it('starts the write, then reads the Post until the new Version is its Text', async () => {
      vi.spyOn(apiService, 'get')
        .mockResolvedValueOnce(read([VERSION], 'writing') as never)
        .mockResolvedValueOnce(read([VERSION, VERSION_TWO], null) as never);

      const adding = postService.addVersion('post_01', 'shorter', 'post', ['the final']);
      await vi.advanceTimersByTimeAsync(WRITING_POLL_MS);
      expect(apiService.get).toHaveBeenCalledTimes(1);
      await vi.advanceTimersByTimeAsync(WRITING_POLL_MS);

      const version = await adding;
      expect(apiService.post).toHaveBeenCalledWith('/posts/post_01/versions', {
        feedback: 'shorter',
        format: 'post',
        text: ['the final'],
      });
      expect(version.number).toBe(2);
      expect(version.parts).toEqual([{ text: 'shorter', charCount: 7, charLimit: 280 }]);
    });

    it('rejects when the write ends with no new Version, which leaves the Text', async () => {
      vi.spyOn(apiService, 'get').mockResolvedValue(read([VERSION], null) as never);

      const adding = postService.addVersion('post_01', 'shorter', 'post', ['the final']);
      const failed = expect(adding).rejects.toBeInstanceOf(VersionNotWritten);
      await vi.advanceTimersByTimeAsync(WRITING_POLL_MS);

      await failed;
    });

    it('waits longer after a read that fails, and stops on a 404', async () => {
      const down = Object.assign(new Error('down'), { response: { status: 502 } });
      const gone = Object.assign(new Error('gone'), { response: { status: 404 } });
      vi.spyOn(apiService, 'get').mockRejectedValueOnce(down).mockRejectedValueOnce(gone);

      const waiting = postService.awaitVersion('post_01', 1);
      const failed = expect(waiting).rejects.toBe(gone);
      await vi.advanceTimersByTimeAsync(WRITING_POLL_MS);
      await vi.advanceTimersByTimeAsync(WRITING_POLL_MS);
      expect(apiService.get).toHaveBeenCalledTimes(1);
      await vi.advanceTimersByTimeAsync(WRITING_POLL_MS);

      await failed;
    });

    it('stops reading once the wait is aborted', async () => {
      vi.spyOn(apiService, 'get').mockResolvedValue(read([VERSION], 'writing') as never);
      const stop = new AbortController();

      const waiting = postService.awaitVersion('post_01', 1, stop.signal);
      const stopped = expect(waiting).rejects.toBeDefined();
      await vi.advanceTimersByTimeAsync(WRITING_POLL_MS);
      stop.abort();
      await vi.advanceTimersByTimeAsync(WRITING_POLL_MS * 4);

      await stopped;
      expect(apiService.get).toHaveBeenCalledTimes(1);
    });
  });
});
