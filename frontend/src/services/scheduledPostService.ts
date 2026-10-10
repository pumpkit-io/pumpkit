import { apiService } from './apiService';

export type ScheduledPostState = 'scheduled' | 'publishing' | 'published' | 'failed';

/** A text set to be published on the User's X account, with its own copy of the text. */
export interface ScheduledPost {
  id: string;
  text: string;
  state: ScheduledPostState;
  publishAt: string;
  publishedAt: string | null;
  /** The post on X, once Published. */
  xPostUrl: string | null;
  /** Why it Failed, in words for the User. */
  failedReason: string | null;
  createdAt: string;
}

interface ScheduledPostApi {
  id: string;
  text: string;
  state: ScheduledPostState;
  publish_at: string;
  published_at: string | null;
  x_post_url: string | null;
  failed_reason: string | null;
  created_at: string;
}

const toScheduledPost = (p: ScheduledPostApi): ScheduledPost => ({
  id: p.id,
  text: p.text,
  state: p.state,
  publishAt: p.publish_at,
  publishedAt: p.published_at,
  xPostUrl: p.x_post_url,
  failedReason: p.failed_reason,
  createdAt: p.created_at,
});

export const scheduledPostService = {
  /** Waiting ones first, soonest first; then Published and Failed ones, newest first. */
  list: async (): Promise<ScheduledPost[]> => {
    const { data } = await apiService.get<{ data: ScheduledPostApi[] }>('/scheduled-posts');
    return data.data.map(toScheduledPost);
  },

  /** Publishes on X before answering: it comes back Published or Failed. */
  postNow: async (text: string): Promise<ScheduledPost> => {
    const { data } = await apiService.post<ScheduledPostApi>('/scheduled-posts', {
      text,
      publish_now: true,
    });
    return toScheduledPost(data);
  },
};
