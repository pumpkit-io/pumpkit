import { readFileSync } from 'node:fs';
import path from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { apiService } from './apiService';
import { briefService, notWrittenIdeas, type Brief, type Idea } from './briefService';

interface OfferedIdeasCase {
  note: string;
  /** Each Idea's id ("whole" for the single-post Idea) and its Post's writing state, or null. */
  ideas: [string, 'written' | 'writing' | 'not_written' | null][];
  offered: string[];
}

// The backend's cases, so the Brief's page offers the Ideas its row on New post counts.
const OFFERED_IDEAS_CASES: OfferedIdeasCase[] = JSON.parse(
  readFileSync(
    path.resolve(__dirname, '../../../backend/tests/posts/offered_ideas_cases.json'),
    'utf8',
  ),
);

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
        status: 'draft',
        publishing: false,
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
  generations_left: 3,
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
        status: 'draft',
        publishing: false,
        text: {
          format: 'post',
          parts: [{ text: 'Shipped.', charCount: 8, charLimit: 280 }],
          firstReply: false,
          versionNumber: 1,
          edited: false,
        },
        textMedia: [[]],
      },
    },
  ],
  generationsLeft: 3,
};

describe('briefService', () => {
  afterEach(() => vi.restoreAllMocks());

  it('plans a brief and reads its ideas and posts', async () => {
    vi.spyOn(apiService, 'post').mockResolvedValue({ data: BRIEF_API } as never);

    expect(await briefService.plan('ship')).toEqual(BRIEF);
    expect(apiService.post).toHaveBeenCalledWith('/briefs', { brief: 'ship' });
  });

  it('reads no status from a write, which answers without one', async () => {
    const [whole, split] = BRIEF_API.ideas;
    const post = { ...split!.post!, status: undefined };
    const answer = { ...BRIEF_API, ideas: [whole, { ...split, post }] };
    vi.spyOn(apiService, 'post').mockResolvedValue({ data: answer } as never);

    const brief = await briefService.write('brief_01', ['idea_1']);

    expect(brief.ideas[1]!.post!.status).toBeNull();
  });

  it('writes the ideas named', async () => {
    vi.spyOn(apiService, 'post').mockResolvedValue({ data: BRIEF_API } as never);

    await briefService.write('brief_01', ['idea_1']);

    expect(apiService.post).toHaveBeenCalledWith('/briefs/brief_01/posts', {
      idea_ids: ['idea_1'],
    });
  });

  it('reads a post being published', async () => {
    const [whole, split] = BRIEF_API.ideas;
    const post = { ...split!.post!, status: 'scheduled', publishing: true };
    const answer = { ...BRIEF_API, ideas: [whole, { ...split, post }] };
    vi.spyOn(apiService, 'get').mockResolvedValue({ data: answer } as never);

    const brief = await briefService.get('brief_01');

    expect(brief.ideas[1]!.post).toMatchObject({ status: 'scheduled', publishing: true });
  });

  it('lists the recent briefs with their posts counted', async () => {
    const get = vi.spyOn(apiService, 'get').mockResolvedValue({
      data: {
        data: [
          {
            id: 'brief_01',
            text_start: 'so I have been testing…',
            posts_written: 2,
            posts_writing: 1,
            posts_not_written: 0,
            ideas_offered: 1,
            post_ids: ['post_01', 'post_02', 'post_03'],
          },
        ],
      },
    } as never);

    expect(await briefService.recent()).toEqual([
      {
        id: 'brief_01',
        textStart: 'so I have been testing…',
        postsWritten: 2,
        postsWriting: 1,
        postsNotWritten: 0,
        ideasOffered: 1,
        postIds: ['post_01', 'post_02', 'post_03'],
      },
    ]);
    expect(get).toHaveBeenCalledWith('/briefs');
  });

  it('reads a brief', async () => {
    vi.spyOn(apiService, 'get').mockResolvedValue({ data: BRIEF_API } as never);

    expect(await briefService.get('brief_01')).toEqual(BRIEF);
    expect(apiService.get).toHaveBeenCalledWith('/briefs/brief_01');
  });
});

describe('notWrittenIdeas', () => {
  const [whole, split] = BRIEF.ideas as [Idea, Idea];
  const ideaOf = ([id, state]: OfferedIdeasCase['ideas'][number]): Idea => ({
    ...(id === 'whole' ? whole : split),
    id,
    post:
      state === null ? null : { ...split.post!, writingState: state === 'written' ? null : state },
  });

  it.each(OFFERED_IDEAS_CASES)('$note', ({ ideas, offered }) => {
    const brief: Brief = { ...BRIEF, ideas: ideas.map(ideaOf) };
    expect(notWrittenIdeas(brief).map((idea) => idea.id)).toEqual(offered);
  });
});
