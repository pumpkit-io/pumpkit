import { apiService } from './apiService';
import type { AllowanceWayOut } from './apiErrors';

/** One count of an Allowance in the current period. A limit of null is no cap. */
export interface UsageCount {
  limit: number | null;
  used: number;
  left: number | null;
}

/** What one unexpired Top-up has left, spent only once the Allowance is used up. */
export interface TopUpUsage {
  generationsLeft: number;
  xPostsLeft: number;
  linkXPostsLeft: number;
  expiresAt: Date;
}

/** What the User has used and has left of the Allowance period holding now. */
export interface AllowanceUsage {
  trial: boolean;
  /** When the period ends: the next reset, or the Trial's end. */
  resetsAt: Date;
  generations: UsageCount;
  xPosts: UsageCount;
  /** Of the X posts, those containing a link. */
  linkXPosts: UsageCount;
  /** What the User can do at a limit before the period resets. */
  wayOut: AllowanceWayOut | null;
  /** The User's Top-ups with something left, first to expire first. */
  topUps: TopUpUsage[];
  mayBuyTopUp: boolean;
}

export interface Usage {
  /** Null where the Instance sells no Plans or the User isn't Subscribed. */
  allowance: AllowanceUsage | null;
}

interface UsageApi {
  allowance: {
    trial: boolean;
    resets_at: string;
    generations: UsageCount;
    x_posts: UsageCount;
    link_x_posts: UsageCount;
    way_out: AllowanceWayOut | null;
    top_ups: {
      generations_left: number;
      x_posts_left: number;
      link_x_posts_left: number;
      expires_at: string;
    }[];
    may_buy_top_up: boolean;
  } | null;
}

export const usageService = {
  get: async (): Promise<Usage> => {
    const { data } = await apiService.get<UsageApi>('/usage');
    const { allowance } = data;
    return {
      allowance: allowance && {
        trial: allowance.trial,
        resetsAt: new Date(allowance.resets_at),
        generations: allowance.generations,
        xPosts: allowance.x_posts,
        linkXPosts: allowance.link_x_posts,
        wayOut: allowance.way_out,
        topUps: allowance.top_ups.map((topUp) => ({
          generationsLeft: topUp.generations_left,
          xPostsLeft: topUp.x_posts_left,
          linkXPostsLeft: topUp.link_x_posts_left,
          expiresAt: new Date(topUp.expires_at),
        })),
        mayBuyTopUp: allowance.may_buy_top_up,
      },
    };
  },
};
