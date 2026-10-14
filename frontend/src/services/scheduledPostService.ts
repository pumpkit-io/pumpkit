import { apiService } from './apiService';

export type ScheduledPostState = 'scheduled' | 'publishing' | 'published' | 'failed';

/** The X Community a Scheduled post goes to. */
export interface Community {
  id: string;
  /** As the User saw it when they picked it; null when it couldn't be looked up. */
  name: string | null;
  /** The Community on X. */
  url: string;
}

/** Where a new Scheduled post goes: the User's profile when `community` is null. */
export interface Destination {
  community: Pick<Community, 'id' | 'name'> | null;
  /** With a Community, whether X also shares it with the account's followers. */
  shareWithFollowers: boolean;
}

/** What an edit changes; anything left out stays as it is. */
export interface ScheduledPostChanges {
  text?: string;
  publishAt?: string;
  /** Null moves it back to the User's profile. */
  community?: Destination['community'];
  shareWithFollowers?: boolean;
}

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
  /** The Community it goes to; null for the User's profile. */
  community: Community | null;
  shareWithFollowers: boolean;
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
  community: Community | null;
  share_with_followers: boolean;
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
  community: p.community,
  shareWithFollowers: p.share_with_followers,
  createdAt: p.created_at,
});

const destinationBody = ({ community, shareWithFollowers }: Destination) => ({
  community,
  share_with_followers: shareWithFollowers,
});

export const scheduledPostService = {
  /** Waiting ones first, soonest first; then Published and Failed ones, newest first. */
  list: async (): Promise<ScheduledPost[]> => {
    const { data } = await apiService.get<{ data: ScheduledPostApi[] }>('/scheduled-posts');
    return data.data.map(toScheduledPost);
  },

  /**
   * Publishes on X before answering: it comes back Published, Failed, or scheduled when X was
   * busy and the publisher will retry. `sourceVersionId` is the Version whose Final the text is.
   */
  postNow: async (
    text: string,
    sourceVersionId: string | undefined,
    destination: Destination,
  ): Promise<ScheduledPost> => {
    const { data } = await apiService.post<ScheduledPostApi>('/scheduled-posts', {
      text,
      publish_now: true,
      source_version_id: sourceVersionId,
      ...destinationBody(destination),
    });
    return toScheduledPost(data);
  },

  /** `publishAt` is an ISO instant on a whole minute; it comes back scheduled. */
  schedule: async (
    text: string,
    publishAt: string,
    sourceVersionId: string | undefined,
    destination: Destination,
  ): Promise<ScheduledPost> => {
    const { data } = await apiService.post<ScheduledPostApi>('/scheduled-posts', {
      text,
      publish_at: publishAt,
      source_version_id: sourceVersionId,
      ...destinationBody(destination),
    });
    return toScheduledPost(data);
  },

  /**
   * For a scheduled or Failed one. A new `publishAt` reschedules it on the X account connected
   * now and puts a Failed one back in scheduled.
   */
  edit: async (id: string, changes: ScheduledPostChanges): Promise<ScheduledPost> => {
    const { data } = await apiService.patch<ScheduledPostApi>(
      `/scheduled-posts/${encodeURIComponent(id)}`,
      {
        text: changes.text,
        publish_at: changes.publishAt,
        // Sent only when given: null moves it back to the profile, absent keeps the Community.
        ...('community' in changes && { community: changes.community }),
        share_with_followers: changes.shareWithFollowers,
      },
    );
    return toScheduledPost(data);
  },

  /** Deletes a scheduled or Failed one. */
  cancel: async (id: string): Promise<void> => {
    await apiService.delete(`/scheduled-posts/${encodeURIComponent(id)}`);
  },
};
