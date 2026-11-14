import { afterEach, describe, expect, it, vi } from 'vitest';
import { apiService } from './apiService';
import { briefService, type Brief } from './briefService';

const PLAN = {
  core_idea: 'Ship small.',
  takeaway: 'Ship this week.',
  funnel: 'middle',
  desired_action: 'bookmark',
  format: 'post',
  length: 'short',
  structure: 'few_lines',
};

const BRIEF_API = {
  id: 'brief_01',
  text: 'ship',
  created_at: '2026-10-10T12:00:30Z',
  ideas: [
    { id: 'idea_whole', posting_order: 1, whole_brief: true, plan: PLAN, post: null },
    {
      id: 'idea_1',
      posting_order: 1,
      whole_brief: false,
      plan: PLAN,
      post: {
        id: 'post_01',
        writing_state: null,
        text: {
          format: 'post',
          parts: [{ text: 'Shipped.', char_count: 8, char_limit: 280, media: [] }],
          first_reply: false,
          version_number: 1,
          edited: false,
        },
      },
    },
  ],
};

const BRIEF: Brief = {
  id: 'brief_01',
  text: 'ship',
  createdAt: '2026-10-10T12:00:30Z',
  ideas: [
    {
      id: 'idea_whole',
      postingOrder: 1,
      wholeBrief: true,
      plan: {
        coreIdea: 'Ship small.',
        takeaway: 'Ship this week.',
        funnel: 'middle',
        desiredAction: 'bookmark',
        format: 'post',
        length: 'short',
        structure: 'few_lines',
      },
      post: null,
    },
    {
      id: 'idea_1',
      postingOrder: 1,
      wholeBrief: false,
      plan: {
        coreIdea: 'Ship small.',
        takeaway: 'Ship this week.',
        funnel: 'middle',
        desiredAction: 'bookmark',
        format: 'post',
        length: 'short',
        structure: 'few_lines',
      },
      post: {
        id: 'post_01',
        writingState: null,
        text: {
          format: 'post',
          parts: [{ text: 'Shipped.', charCount: 8, charLimit: 280 }],
          firstReply: false,
          versionNumber: 1,
          edited: false,
        },
      },
    },
  ],
};

describe('briefService', () => {
  afterEach(() => vi.restoreAllMocks());

  it('plans a brief and reads its ideas and posts', async () => {
    vi.spyOn(apiService, 'post').mockResolvedValue({ data: BRIEF_API } as never);

    expect(await briefService.plan('ship')).toEqual(BRIEF);
    expect(apiService.post).toHaveBeenCalledWith('/briefs', { brief: 'ship' });
  });

  it('writes the ideas named', async () => {
    vi.spyOn(apiService, 'post').mockResolvedValue({ data: BRIEF_API } as never);

    await briefService.write('brief_01', ['idea_1']);

    expect(apiService.post).toHaveBeenCalledWith('/briefs/brief_01/posts', {
      idea_ids: ['idea_1'],
    });
  });

  it('reads a brief', async () => {
    vi.spyOn(apiService, 'get').mockResolvedValue({ data: BRIEF_API } as never);

    expect(await briefService.get('brief_01')).toEqual(BRIEF);
    expect(apiService.get).toHaveBeenCalledWith('/briefs/brief_01');
  });
});
