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

/** A Post as its page shows it, read from the server. */
export interface PostDetail extends Post {
  /** Null for a Post written before Briefs were planned. */
  plan: Plan | null;
  /** Null only for a Post whose first Version failed. */
  text: PostText | null;
  status: PostStatus;
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

interface PostTextApi {
  format: Format;
  parts: (PartApi & { media: MediaApi[] })[];
  first_reply: boolean;
  version_number: number;
  edited: boolean;
}

interface PlanApi {
  core_idea: string;
  takeaway: string;
  funnel: Funnel;
  desired_action: DesiredAction;
  format: Format;
  length: Length | null;
  structure: string;
}

interface PostDetailApi extends PostApi {
  plan: PlanApi | null;
  text: PostTextApi | null;
  status: PostStatus;
  scheduled_post: ScheduledPostApi | null;
}

const toPlan = (p: PlanApi): Plan => ({
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

const toText = (t: PostTextApi): PostText => ({
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
  /** Open to a User who isn't Subscribed, so their history stays readable. */
  get: async (postId: string): Promise<PostDetail> => {
    const { data } = await apiService.get<PostDetailApi>(`/posts/${encodeURIComponent(postId)}`);
    return {
      id: data.id,
      brief: data.brief,
      plan: data.plan ? toPlan(data.plan) : null,
      text: data.text ? toText(data.text) : null,
      versions: data.versions.map(toVersion),
      status: data.status,
      scheduledPost: data.scheduled_post ? toScheduledPost(data.scheduled_post) : null,
      textMedia: data.text ? data.text.parts.map((p) => p.media.map(toMedia)) : [],
    };
  },
  /** Writes the first Version before answering, which can take a minute or two. */
  start: async (brief: string, format: Format): Promise<Post> => {
    const { data } = await apiService.post<PostApi>('/posts', { brief, format });
    return { id: data.id, brief: data.brief, versions: data.versions.map(toVersion) };
  },
  /**
   * Writes the next Version from Feedback on the Text before answering, which can take a minute
   * or two. `text` is every Part on screen: the server refuses it while an edit isn't saved yet.
   */
  addVersion: async (
    postId: string,
    feedback: string,
    format: Format,
    text: string[],
  ): Promise<Version> => {
    const { data } = await apiService.post<VersionApi>(`/posts/${postId}/versions`, {
      feedback,
      format,
      text,
    });
    return toVersion(data);
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
