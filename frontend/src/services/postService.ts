import { errorStatus } from './apiErrors';
import { apiService } from './apiService';
import { toMedia, type Media, type MediaApi } from './mediaService';
import {
  toScheduledPost,
  type Community,
  type ScheduledPost,
  type ScheduledPostApi,
  type ScheduledPostState,
} from './scheduledPostService';

/** The shape of a Version's text: a single X post, or a Thread. */
export type Format = 'post' | 'thread';
export const FORMAT_POST: Format = 'post';
export const FORMAT_THREAD: Format = 'thread';

/** The Format of Parts that record none, as a Scheduled post's: a first reply keeps it a post. */
export function formatOf(partCount: number, firstReply: boolean): Format {
  return partCount > 1 && !firstReply ? FORMAT_THREAD : FORMAT_POST;
}

/** One Part of a Version's text, in its place in the order. */
export interface Part {
  text: string;
  /** Counted by the backend, the way the limit counts; a JS string's length disagrees on emoji. */
  charCount: number;
  charLimit: number;
}

/** One round of a Post's text, the text meant for X. */
export interface Version {
  /** What a Scheduled post copied from this Version records as its source. */
  id: string;
  number: number;
  /** Null for the first Version, which comes from the Brief. */
  feedback: string | null;
  format: Format;
  /** A single X post has one Part, or two with its first reply. */
  parts: Part[];
  /** Whether the last Part is the single post's first reply (ADR 0027). */
  firstReply: boolean;
  /** When Pumpkit wrote it. */
  createdAt: string;
}

/** The one text a Post has at any time, the text meant for X (ADR 0016). */
export interface PostText {
  format: Format;
  parts: Part[];
  /** Whether the last Part is the single post's first reply, posted as a reply to it. */
  firstReply: boolean;
  /** The Version it came from: the last one written or restored. */
  versionNumber: number;
  /** Whether the User changed it since it came from that Version. */
  edited: boolean;
}

export interface Post {
  id: string;
  brief: string;
  versions: Version[];
}

/** Where a Post stands, from its one Scheduled post (ADR 0015): none makes it a Draft. */
export type PostStatus = 'draft' | 'scheduled' | 'published' | 'failed';

export type Funnel = 'top' | 'middle' | 'bottom';
export type DesiredAction =
  | 'dwell_time'
  | 'reply'
  | 'bookmark'
  | 'repost'
  | 'share'
  | 'follow'
  | 'trust'
  | 'click'
  | 'DM'
  | 'sign-up'
  | 'buy';
export type Length = 'short' | 'medium' | 'long';

/** What Pumpkit decided about a Post before writing it (ADR 0025). */
export interface Plan {
  coreIdea: string;
  takeaway: string;
  /** Who the Post is for: `top` for reach, `middle` for trust, `bottom` for conversion. */
  funnel: Funnel;
  desiredAction: DesiredAction;
  format: Format;
  /** Null for a Thread. */
  length: Length | null;
  structure: string;
}

/**
 * Whether Pumpkit is writing a Post's first Version, or couldn't write it and offers Retry
 * (ADR 0026). A write that outlives the backend's timeout reads as `not_written`.
 */
export type WritingState = 'writing' | 'not_written';

/** How often a page reads a Post again while one of its Versions is being written. */
export const WRITING_POLL_MS = 3_000;
/** The longest wait between reads, which doubles after each read that fails. */
export const WRITING_POLL_MAX_MS = 60_000;

/** How long to wait before the next read while a Version is written, after `failures` in a row. */
export function pollDelay(failures: number): number {
  return Math.min(WRITING_POLL_MS * 2 ** failures, WRITING_POLL_MAX_MS);
}

/** Feedback whose Version Pumpkit couldn't write, as it was sent, to send again. */
export interface FailedFeedback {
  feedback: string;
  format: Format;
}

/** Feedback's write failed or outlived the backend's timeout: the Text is as it was. */
export class VersionNotWritten extends Error {
  constructor(readonly failedFeedback: FailedFeedback | null = null) {
    super("Pumpkit couldn't write the next version, so your text hasn't changed. Try again.");
    this.name = 'VersionNotWritten';
  }
}

/** Resolves after `ms`, or rejects once `signal` aborts. */
function pause(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) return reject(signal.reason);
    const timer = setTimeout(() => {
      signal?.removeEventListener('abort', stop);
      resolve();
    }, ms);
    const stop = () => {
      clearTimeout(timer);
      reject(signal?.reason);
    };
    signal?.addEventListener('abort', stop, { once: true });
  });
}

/**
 * Where a Post comes among its Brief's Posts, in the order of their Ideas: every Post counts,
 * written, being written or not, and an Idea not written doesn't.
 */
export interface PlaceInBrief {
  /** From 1. */
  position: number;
  postCount: number;
  previousPostId: string | null;
  nextPostId: string | null;
}

interface PlaceInBriefApi {
  position: number;
  post_count: number;
  previous_post_id: string | null;
  next_post_id: string | null;
}

const toPlaceInBrief = (p: PlaceInBriefApi): PlaceInBrief => ({
  position: p.position,
  postCount: p.post_count,
  previousPostId: p.previous_post_id,
  nextPostId: p.next_post_id,
});

/** A Post with no Text yet: no Draft, no status, only its Brief, Plan and writing state. */
export interface UnwrittenPost {
  id: string;
  brief: string;
  briefId: string;
  placeInBrief: PlaceInBrief;
  plan: Plan | null;
  writingState: WritingState;
}

export function isUnwritten(post: PostDetail | UnwrittenPost): post is UnwrittenPost {
  return 'writingState' in post;
}

/** A Post as its page shows it, read from the server. */
export interface PostDetail extends Post {
  briefId: string;
  placeInBrief: PlaceInBrief;
  /** Null for a Post written before Briefs were planned. */
  plan: Plan | null;
  /** Never null from `get`: a Post with no Text reads as an `UnwrittenPost`. */
  text: PostText | null;
  status: PostStatus;
  /** True while Feedback's Version is being written: the Text can't change until it is. */
  writing: boolean;
  /** The last Feedback when its Version couldn't be written, until the User moves on. */
  failedFeedback: FailedFeedback | null;
  /** Null while the Post is a Draft. */
  scheduledPost: ScheduledPost | null;
  /**
   * Each of the Text's Parts' Media, in order, as the Post was read. Kept apart from the Text,
   * since undo, redo, restoring and Feedback change only its words.
   */
  textMedia: Media[][];
}

/** How many Posts each status holds, for the Posts tabs and the sidebar's Failed badge. */
export type PostCounts = Record<PostStatus, number>;

/** What a listed Post shows of its Scheduled post. */
export interface ScheduledPostSummary {
  id: string;
  state: ScheduledPostState;
  publishAt: string;
  publishedAt: string | null;
  /** Null for the User's profile. */
  community: Community | null;
  shareWithFollowers: boolean;
  failedReason: string | null;
  /** The first Part on X, once it is live. */
  xPostUrl: string | null;
  /** As on `ScheduledPost`. */
  posting: boolean;
}

/** A Post as the Posts tabs list it. */
export interface PostListItem {
  id: string;
  brief: string;
  briefId: string;
  placeInBrief: PlaceInBrief;
  status: PostStatus;
  /** The Scheduled post's text when it has one, else the latest Version's. */
  parts: string[];
  format: Format;
  /** Whether the last Part is the single post's first reply. */
  firstReply: boolean;
  versionCount: number;
  latestVersionAt: string;
  scheduledPost: ScheduledPostSummary | null;
}

export interface PostsPage {
  posts: PostListItem[];
  counts: PostCounts;
  /** Null on the last page. */
  nextOffset: number | null;
}

interface ScheduledPostSummaryApi {
  id: string;
  state: ScheduledPostState;
  publish_at: string;
  published_at: string | null;
  community: Community | null;
  share_with_followers: boolean;
  failed_reason: string | null;
  x_post_url: string | null;
  posting: boolean;
}

interface PostsPageApi {
  data: {
    id: string;
    brief: string;
    brief_id: string;
    place_in_brief: PlaceInBriefApi;
    status: PostStatus;
    parts: string[];
    format: Format;
    first_reply: boolean;
    version_count: number;
    latest_version_at: string;
    scheduled_post: ScheduledPostSummaryApi | null;
  }[];
  counts: PostCounts;
  next_offset: number | null;
}

const toSummary = (s: ScheduledPostSummaryApi): ScheduledPostSummary => ({
  id: s.id,
  state: s.state,
  publishAt: s.publish_at,
  publishedAt: s.published_at,
  community: s.community,
  shareWithFollowers: s.share_with_followers,
  failedReason: s.failed_reason,
  xPostUrl: s.x_post_url,
  posting: s.posting,
});

/** How many Posts a page of the Posts tabs holds. */
export const POSTS_PAGE_SIZE = 20;

interface PartApi {
  text: string;
  char_count: number;
  char_limit: number;
}

interface VersionApi {
  id: string;
  number: number;
  feedback: string | null;
  format: Format;
  parts: PartApi[];
  first_reply: boolean;
  created_at: string;
}

interface PostApi {
  id: string;
  brief: string;
  versions: VersionApi[];
}

interface StartedPostApi extends PostApi {
  plan: PlanApi | null;
  writing_state: 'writing';
}

export interface PostTextApi {
  format: Format;
  parts: (PartApi & { media: MediaApi[] })[];
  first_reply: boolean;
  version_number: number;
  edited: boolean;
}

export interface PlanApi {
  core_idea: string;
  takeaway: string;
  funnel: Funnel;
  desired_action: DesiredAction;
  format: Format;
  length: Length | null;
  structure: string;
}

interface PostDetailApi extends PostApi {
  brief_id: string;
  place_in_brief: PlaceInBriefApi;
  plan: PlanApi | null;
  text: PostTextApi | null;
  writing_state: WritingState | null;
  failed_feedback: FailedFeedback | null;
  /** Null until the first Version is written. */
  status: PostStatus | null;
  scheduled_post: ScheduledPostApi | null;
}

export const toPlan = (p: PlanApi): Plan => ({
  coreIdea: p.core_idea,
  takeaway: p.takeaway,
  funnel: p.funnel,
  desiredAction: p.desired_action,
  format: p.format,
  length: p.length,
  structure: p.structure,
});

const toPart = (p: PartApi): Part => ({
  text: p.text,
  charCount: p.char_count,
  charLimit: p.char_limit,
});

const toVersion = (v: VersionApi): Version => ({
  id: v.id,
  number: v.number,
  feedback: v.feedback,
  format: v.format,
  parts: v.parts.map(toPart),
  firstReply: v.first_reply,
  createdAt: v.created_at,
});

export const toText = (t: PostTextApi): PostText => ({
  format: t.format,
  parts: t.parts.map(toPart),
  firstReply: t.first_reply,
  versionNumber: t.version_number,
  edited: t.edited,
});

/** The Text a new Version gives its Post: the server sets it from every Version it writes. */
export function textOf(version: Version): PostText {
  return {
    format: version.format,
    parts: version.parts,
    firstReply: version.firstReply,
    versionNumber: version.number,
    edited: false,
  };
}

/** A Post just started, which the response of starting it doesn't place in its Brief. */
export type StartedPost = Omit<UnwrittenPost, 'briefId' | 'placeInBrief'>;

const startedPost = (data: StartedPostApi): StartedPost => ({
  id: data.id,
  brief: data.brief,
  plan: data.plan ? toPlan(data.plan) : null,
  writingState: data.writing_state,
});

/** The backend refuses a longer Brief; the UI shows a counter as it gets close. */
export const BRIEF_MAX_CHARS = 200_000;
/** The backend refuses longer Feedback; the UI shows a counter as it gets close. */
export const FEEDBACK_MAX_CHARS = 100_000;

export const postService = {
  /** A page of the Posts in `status`, with every status's count. Open like `get`. */
  list: async (status: PostStatus, offset = 0, limit = POSTS_PAGE_SIZE): Promise<PostsPage> => {
    const { data } = await apiService.get<PostsPageApi>('/posts', {
      params: { status, offset, limit },
    });
    return {
      posts: data.data.map((p) => ({
        id: p.id,
        brief: p.brief,
        briefId: p.brief_id,
        placeInBrief: toPlaceInBrief(p.place_in_brief),
        status: p.status,
        parts: p.parts,
        format: p.format,
        firstReply: p.first_reply,
        versionCount: p.version_count,
        latestVersionAt: p.latest_version_at,
        scheduledPost: p.scheduled_post ? toSummary(p.scheduled_post) : null,
      })),
      counts: data.counts,
      nextOffset: data.next_offset,
    };
  },
  /**
   * The Post as its page shows it, or as an `UnwrittenPost` until its first Version is written.
   * Open to a User who isn't Subscribed, so their history stays readable.
   */
  get: async (postId: string): Promise<PostDetail | UnwrittenPost> => {
    const { data } = await apiService.get<PostDetailApi>(`/posts/${encodeURIComponent(postId)}`);
    const plan = data.plan ? toPlan(data.plan) : null;
    const place = { briefId: data.brief_id, placeInBrief: toPlaceInBrief(data.place_in_brief) };
    if (data.status === null)
      return {
        id: data.id,
        brief: data.brief,
        ...place,
        plan,
        writingState: data.writing_state ?? 'not_written',
      };
    return {
      id: data.id,
      brief: data.brief,
      ...place,
      plan,
      text: data.text ? toText(data.text) : null,
      versions: data.versions.map(toVersion),
      status: data.status,
      writing: data.writing_state === 'writing',
      failedFeedback: data.failed_feedback,
      scheduledPost: data.scheduled_post ? toScheduledPost(data.scheduled_post) : null,
      textMedia: data.text ? data.text.parts.map((p) => p.media.map(toMedia)) : [],
    };
  },
  /** Writes the first Version of a Post Pumpkit couldn't write again, from the same Plan. */
  retry: async (postId: string): Promise<StartedPost> => {
    const { data } = await apiService.post<StartedPostApi>(
      `/posts/${encodeURIComponent(postId)}/retry`,
    );
    return startedPost(data);
  },
  /**
   * Writes the next Version from Feedback on the Text, in the background, and resolves with it
   * once it is the Text: a minute or two. `text` is every Part on screen: the server refuses it
   * while an edit isn't saved yet.
   */
  addVersion: async (
    postId: string,
    feedback: string,
    format: Format,
    text: string[],
    signal?: AbortSignal,
  ): Promise<Version> => {
    const { data } = await apiService.post<PostDetailApi>(`/posts/${postId}/versions`, {
      feedback,
      format,
      text,
    });
    const after = Math.max(0, ...data.versions.map((v) => v.number));
    return postService.awaitVersion(postId, after, signal);
  },
  /**
   * Reads the Post until no Version is being written, and resolves with the Version written after
   * Version `after`. Rejects with `VersionNotWritten` when the write failed or timed out, which
   * leaves the Text as it was, and with the read's error on a 404 or 403.
   */
  awaitVersion: async (postId: string, after: number, signal?: AbortSignal): Promise<Version> => {
    let failures = 0;
    for (;;) {
      await pause(pollDelay(failures), signal);
      let post: PostDetail | UnwrittenPost;
      try {
        post = await postService.get(postId);
      } catch (e) {
        const status = errorStatus(e);
        if (status === 404 || status === 403) throw e;
        failures += 1;
        continue;
      }
      failures = 0;
      if (!isUnwritten(post) && post.writing) continue;
      const versions = isUnwritten(post) ? [] : post.versions.filter((v) => v.number > after);
      const written = versions[versions.length - 1];
      if (written) return written;
      throw new VersionNotWritten(isUnwritten(post) ? null : post.failedFeedback);
    }
  },
  /** Stops showing the Post's last Feedback as one Pumpkit couldn't write. */
  dismissFailedFeedback: async (postId: string): Promise<void> => {
    await apiService.delete(`/posts/${postId}/failed-feedback`);
  },
  /**
   * Stores the User's edit of the Post's Text, every Part in order, as typed, and whether the
   * last is a single post's first reply, which the User may add or remove. Saving the same Parts
   * again changes nothing, so a failed save can be retried as it is.
   */
  saveText: async (postId: string, parts: string[], firstReply: boolean): Promise<PostText> => {
    const { data } = await apiService.put<PostTextApi>(
      `/posts/${encodeURIComponent(postId)}/text`,
      { parts, first_reply: firstReply },
    );
    return toText(data);
  },
  /** Makes the Version the Post's Text again, which writes nothing and answers at once. */
  restoreVersion: async (postId: string, versionNumber: number): Promise<PostText> => {
    const { data } = await apiService.post<PostTextApi>(
      `/posts/${encodeURIComponent(postId)}/versions/${versionNumber}/restore`,
    );
    return toText(data);
  },
};
