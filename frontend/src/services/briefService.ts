import { apiService } from './apiService';
import { toMedia, type Media } from './mediaService';
import {
  toPlan,
  toText,
  type Plan,
  type PlanApi,
  type PostStatus,
  type PostText,
  type PostTextApi,
  type WritingState,
} from './postService';

/** An Idea's Post as its Brief's page shows it. */
export interface BriefPost {
  id: string;
  /** Null once its first Version is written. */
  writingState: WritingState | null;
  /**
   * From its Scheduled post (ADR 0015); null until its first Version is written, and in the
   * answer to a write, which doesn't read it.
   */
  status: PostStatus | null;
  /** Null until its first Version is written. */
  text: PostText | null;
  /** Each of the Text's Parts' Media, in order, for "Post to…" to send. */
  textMedia: Media[][];
}

/** One Post the planner proposed for a Brief, written or not (ADR 0025). */
export interface Idea {
  id: string;
  /** Where it comes among the Ideas posted with it, from 1. */
  postingOrder: number;
  /** True for the single-post Idea, the one post covering the whole Brief. */
  wholeBrief: boolean;
  plan: Plan | null;
  /** Null until the User writes it. */
  post: BriefPost | null;
}

export interface Brief {
  id: string;
  text: string;
  createdAt: string;
  /** The single-post Idea first, then the split Ideas in posting order. */
  ideas: Idea[];
  /**
   * The Posts the User can still have written, Top-ups included and writes in progress taken out,
   * as the server checks a write; null with no cap.
   */
  generationsLeft: number | null;
}

interface BriefApi {
  id: string;
  text: string;
  created_at: string;
  ideas: {
    id: string;
    posting_order: number;
    whole_brief: boolean;
    plan: PlanApi | null;
    post: {
      id: string;
      writing_state: WritingState | null;
      status?: PostStatus | null;
      text: PostTextApi | null;
    } | null;
  }[];
  generations_left: number | null;
}

const toBrief = (data: BriefApi): Brief => ({
  id: data.id,
  text: data.text,
  createdAt: data.created_at,
  ideas: data.ideas.map((idea) => ({
    id: idea.id,
    postingOrder: idea.posting_order,
    wholeBrief: idea.whole_brief,
    plan: idea.plan ? toPlan(idea.plan) : null,
    post: idea.post && {
      id: idea.post.id,
      writingState: idea.post.writing_state,
      status: idea.post.status ?? null,
      text: idea.post.text ? toText(idea.post.text) : null,
      textMedia: idea.post.text ? idea.post.text.parts.map((p) => p.media.map(toMedia)) : [],
    },
  })),
  generationsLeft: data.generations_left,
});

/** The split Ideas, in posting order; none when the Brief holds one idea. */
export function splitIdeas(brief: Brief): Idea[] {
  return brief.ideas.filter((idea) => !idea.wholeBrief);
}

/** The single-post Idea, which covers the whole Brief. */
export function wholeBriefIdea(brief: Brief): Idea {
  const idea = brief.ideas.find((i) => i.wholeBrief);
  if (!idea) throw new Error('A planned brief always has its single-post idea.');
  return idea;
}

/** The Posts written or being written from the Brief, in the order of its Ideas. */
export function briefPosts(brief: Brief): { idea: Idea; post: BriefPost }[] {
  return brief.ideas.flatMap((idea) => (idea.post ? [{ idea, post: idea.post }] : []));
}

/**
 * The Ideas the Brief's page offers to write. The single-post Idea and the split Ideas are
 * alternatives, so once a Post exists only Ideas of its kind are offered; while none does, every
 * split Idea in posting order and then the single-post one.
 */
export function notWrittenIdeas(brief: Brief): Idea[] {
  const unwritten = brief.ideas.filter((idea) => !idea.post);
  const first = brief.ideas.find((idea) => idea.post);
  if (first) return unwritten.filter((idea) => idea.wholeBrief === first.wholeBrief);
  return [
    ...unwritten.filter((idea) => !idea.wholeBrief),
    ...unwritten.filter((idea) => idea.wholeBrief),
  ];
}

export const briefService = {
  /**
   * Plans the Brief and answers with its Ideas. With no split Ideas, the single-post Idea's Post
   * is already being written when the User had room for it; otherwise nothing is written until
   * `write`.
   */
  plan: async (brief: string): Promise<Brief> => {
    const { data } = await apiService.post<BriefApi>('/briefs', { brief });
    return toBrief(data);
  },
  /** The Brief with its Ideas and their Posts as they are now. */
  get: async (briefId: string): Promise<Brief> => {
    const { data } = await apiService.get<BriefApi>(`/briefs/${encodeURIComponent(briefId)}`);
    return toBrief(data);
  },
  /** Starts writing a Post of each Idea, in the background, and answers with the Brief. */
  write: async (briefId: string, ideaIds: string[]): Promise<Brief> => {
    const { data } = await apiService.post<BriefApi>(
      `/briefs/${encodeURIComponent(briefId)}/posts`,
      { idea_ids: ideaIds },
    );
    return toBrief(data);
  },
};
