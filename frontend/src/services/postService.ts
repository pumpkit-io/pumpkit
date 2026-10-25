import { apiService } from './apiService';

/** A machine-written pattern the slop check found in a Final. */
export interface Tell {
  name: string;
  description: string;
}

/** The shape of a Version's text: a single X post, or a Thread. */
export type Format = 'post' | 'thread';

/** One Part of a Final, in its place in the order. */
export interface Part {
  text: string;
  /** Counted by the backend, the way the limit counts; a JS string's length disagrees on emoji. */
  charCount: number;
  charLimit: number;
}

/** One round of a Post's text: the Draft Pumpkit wrote and the Final meant for X. */
export interface Version {
  /** What a Scheduled post made from this Version's Final records as its source. */
  id: string;
  number: number;
  /** Null for the first Version, which comes from the Brief. */
  feedback: string | null;
  format: Format;
  /** A single X post has one Part. */
  draftParts: string[];
  parts: Part[];
  /** Found in any Part of the Final. */
  tells: Tell[];
}

export interface Post {
  id: string;
  brief: string;
  versions: Version[];
}

interface VersionApi {
  id: string;
  number: number;
  feedback: string | null;
  format: Format;
  draft_parts: string[];
  parts: { text: string; char_count: number; char_limit: number }[];
  tells: Tell[];
}

interface PostApi {
  id: string;
  brief: string;
  versions: VersionApi[];
}

const toVersion = (v: VersionApi): Version => ({
  id: v.id,
  number: v.number,
  feedback: v.feedback,
  format: v.format,
  draftParts: v.draft_parts,
  parts: v.parts.map((p) => ({ text: p.text, charCount: p.char_count, charLimit: p.char_limit })),
  tells: v.tells,
});

/** The backend refuses a longer Brief; the UI shows a counter as it gets close. */
export const BRIEF_MAX_CHARS = 200_000;
/** The backend refuses longer Feedback; the UI shows a counter as it gets close. */
export const FEEDBACK_MAX_CHARS = 100_000;

export const postService = {
  /** Writes the first Version before answering, which can take a minute or two. */
  start: async (brief: string): Promise<Post> => {
    const { data } = await apiService.post<PostApi>('/posts', { brief });
    return { id: data.id, brief: data.brief, versions: data.versions.map(toVersion) };
  },
  /** Writes the next Version from Feedback before answering, which can take a minute or two. */
  addVersion: async (postId: string, feedback: string): Promise<Version> => {
    const { data } = await apiService.post<VersionApi>(`/posts/${postId}/versions`, { feedback });
    return toVersion(data);
  },
};
