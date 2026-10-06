import { apiService } from './apiService';

/** A machine-written pattern the slop check found in a Final. */
export interface Tell {
  name: string;
  description: string;
}

/** One round of a Post's text: the Draft Pumpkit wrote and the Final meant for X. */
export interface Version {
  number: number;
  /** Null for the first Version, which comes from the Brief. */
  feedback: string | null;
  draft: string;
  final: string;
  /** Counted by the backend, the way the limit counts; a JS string's length disagrees on emoji. */
  finalCharCount: number;
  finalCharLimit: number;
  tells: Tell[];
}

export interface Post {
  id: string;
  brief: string;
  versions: Version[];
}

interface VersionApi {
  number: number;
  feedback: string | null;
  draft: string;
  final: string;
  final_char_count: number;
  final_char_limit: number;
  tells: Tell[];
}

interface PostApi {
  id: string;
  brief: string;
  versions: VersionApi[];
}

const toVersion = (v: VersionApi): Version => ({
  number: v.number,
  feedback: v.feedback,
  draft: v.draft,
  final: v.final,
  finalCharCount: v.final_char_count,
  finalCharLimit: v.final_char_limit,
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
