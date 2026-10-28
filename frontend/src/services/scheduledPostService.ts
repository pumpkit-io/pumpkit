import { apiService } from './apiService';

export type ScheduledPostState = 'scheduled' | 'publishing' | 'published' | 'failed';

/** The X Community a Scheduled post goes to. */
export interface Community {
  id: string;
  /** As Pumpkit looked it up on X; null when it couldn't be. */
  name: string | null;
  /** The Community on X. */
  url: string;
}

/** The Version whose text the server copies: a Scheduled post is never typed (ADR 0015). */
export interface ScheduledPostSource {
  sourceVersionId: string;
}

/** Where a new Scheduled post goes: the User's profile when `community` is null. */
export interface Destination {
  community: Pick<Community, 'id' | 'name'> | null;
  /** With a Community, whether X also shares it with the account's followers. */
  shareWithFollowers: boolean;
}

/** What an edit changes; anything left out stays as it is. */
export interface ScheduledPostChanges {
  /** Every Part in order, the live ones first and unchanged; the others replace those not live. */
  parts?: string[];
  /** A Version of the same Post, in place of `parts`: its Parts after the live ones go out. */
  sourceVersionId?: string;
  publishAt?: string;
  /** Publishes it within the request, in place of `publishAt`. */
  publishNow?: boolean;
  /** Null moves it back to the User's profile. */
  community?: Destination['community'];
  shareWithFollowers?: boolean;
}

/** One X post of a Scheduled post, in its place in the order. */
export interface ScheduledPostPart {
  text: string;
  /** Whether X has accepted it. */
  live: boolean;
  /** This Part on X, once live. */
  xPostUrl: string | null;
}

/** A text set to be published on the User's X account, with its own copy of the text. */
export interface ScheduledPost {
  id: string;
  /** In the order they go out; one Part is a single X post. */
  parts: ScheduledPostPart[];
  state: ScheduledPostState;
  publishAt: string;
  publishedAt: string | null;
  /** The first Part on X, once Published. */
  xPostUrl: string | null;
  /** Why it Failed, in words for the User. */
  failedReason: string | null;
  /** The Version whose text it copied; null only for one typed before ADR 0015. */
  sourceVersionId: string | null;
  /** The Community it goes to; null for the User's profile. */
  community: Community | null;
  shareWithFollowers: boolean;
  createdAt: string;
}

export interface ScheduledPostApi {
  id: string;
  parts: { text: string; live: boolean; x_post_url: string | null }[];
  state: ScheduledPostState;
  publish_at: string;
  published_at: string | null;
  x_post_url: string | null;
  failed_reason: string | null;
  source_version_id: string | null;
  community: Community | null;
  share_with_followers: boolean;
  created_at: string;
}

export const toScheduledPost = (p: ScheduledPostApi): ScheduledPost => ({
  id: p.id,
  parts: p.parts.map((part) => ({ text: part.text, live: part.live, xPostUrl: part.x_post_url })),
  state: p.state,
  publishAt: p.publish_at,
  publishedAt: p.published_at,
  xPostUrl: p.x_post_url,
  failedReason: p.failed_reason,
  sourceVersionId: p.source_version_id,
  community: p.community,
  shareWithFollowers: p.share_with_followers,
  createdAt: p.created_at,
});

const postTextBody = (post: ScheduledPostSource) => ({ source_version_id: post.sourceVersionId });

// The server looks up the Community's name itself, so only its ID goes.
const destinationBody = ({ community, shareWithFollowers }: Destination) => ({
  community: community?.id ?? null,
  share_with_followers: shareWithFollowers,
});

export const scheduledPostService = {
  /**
   * The Communities the User posted to before on the connected X account, most recently used
   * first, each under the latest name stored for it.
   */
  pastCommunities: async (): Promise<Community[]> => {
    const { data } = await apiService.get<{ data: Community[] }>('/scheduled-posts/communities');
    return data.data;
  },

  /** Waiting ones first, soonest first; then Published and Failed ones, newest first. */
  list: async (): Promise<ScheduledPost[]> => {
    const { data } = await apiService.get<{ data: ScheduledPostApi[] }>('/scheduled-posts');
    return data.data.map(toScheduledPost);
  },

  /**
   * Publishes on X before answering: it comes back Published, Failed, or scheduled when X was
   * busy and the publisher will retry.
   */
  postNow: async (post: ScheduledPostSource, destination: Destination): Promise<ScheduledPost> => {
    const { data } = await apiService.post<ScheduledPostApi>('/scheduled-posts', {
      ...postTextBody(post),
      publish_now: true,
      ...destinationBody(destination),
    });
    return toScheduledPost(data);
  },

  /** `publishAt` is an ISO instant on a whole minute; it comes back scheduled. */
  schedule: async (
    post: ScheduledPostSource,
    publishAt: string,
    destination: Destination,
  ): Promise<ScheduledPost> => {
    const { data } = await apiService.post<ScheduledPostApi>('/scheduled-posts', {
      ...postTextBody(post),
      publish_at: publishAt,
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
        parts: changes.parts,
        source_version_id: changes.sourceVersionId,
        publish_at: changes.publishAt,
        publish_now: changes.publishNow,
        // Sent only when given: null moves it back to the profile, absent keeps the Community.
        ...('community' in changes && { community: changes.community?.id ?? null }),
        share_with_followers: changes.shareWithFollowers,
      },
    );
    return toScheduledPost(data);
  },

  /**
   * The Community a pasted URL or ID names, with its name on X, or a null name when it can't be
   * read. Fails with a 404 when X has no such Community.
   */
  lookUpCommunity: async (pasted: string): Promise<Community> => {
    const { data } = await apiService.post<Community>('/community-lookups', { pasted });
    return data;
  },

  /** Deletes a scheduled or Failed one. */
  cancel: async (id: string): Promise<void> => {
    await apiService.delete(`/scheduled-posts/${encodeURIComponent(id)}`);
  },
};
