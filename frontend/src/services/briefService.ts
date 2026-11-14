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
  /** Scheduled and being published now. */
  publishing: boolean;
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

/** A Brief as New post lists it, with its Posts counted (ADR 0025). */
export interface RecentBrief {
  id: string;
  /** The text on one line, cut with "…" when longer. */
  textStart: string;
  createdAt: string;
  postsWritten: number;
  postsWriting: number;
  /** Posts whose first Version failed or was lost. */
  postsNotWritten: number;
  /** The Ideas its page offers under "Not written". */
  ideasOffered: number;
  /** Its Posts in its order, written or not. */
  postIds: string[];
}

interface RecentBriefApi {
  id: string;
  text_start: string;
  created_at: string;
  posts_written: number;
  posts_writing: number;
  posts_not_written: number;
  ideas_offered: number;
  post_ids: string[];
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
      publishing?: boolean;
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
      publishing: idea.post.publishing ?? false,
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
 * The Ideas the Brief's page offers to write (ADR 0025). The single-post Idea and the split Ideas
 * are alternatives, so once a kind has a Post only Ideas of that kind are offered, the split ones
 * when both have; while none has, every split Idea in posting order and then the single-post one.
 * `posts/brief_reading.offered_ideas` counts them the same way for the recent Briefs.
 */
export function notWrittenIdeas(brief: Brief): Idea[] {
  const unwritten = brief.ideas.filter((idea) => !idea.post);
  const split = unwritten.filter((idea) => !idea.wholeBrief);
  const written = briefPosts(brief);
  if (written.some(({ idea }) => !idea.wholeBrief)) return split;
  if (written.length > 0) return [];
  return [...split, ...unwritten.filter((idea) => idea.wholeBrief)];
}

/**
 * The Post a Brief opens on in place of its page: its only Post, when no Idea is left to offer
 * (ADR 0025). Null when it opens on its page.
 */
export function lonePost<T>(posts: readonly T[], offered: number): T | null {
  const [only] = posts;
  return only !== undefined && posts.length === 1 && offered === 0 ? only : null;
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
  /** The User's latest ten Briefs, newest first. */
  recent: async (): Promise<RecentBrief[]> => {
    const { data } = await apiService.get<{ data: RecentBriefApi[] }>('/briefs');
    return data.data.map((brief) => ({
      id: brief.id,
      textStart: brief.text_start,
      createdAt: brief.created_at,
      postsWritten: brief.posts_written,
      postsWriting: brief.posts_writing,
      postsNotWritten: brief.posts_not_written,
      ideasOffered: brief.ideas_offered,
      postIds: brief.post_ids,
    }));
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
