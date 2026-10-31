import { apiService } from './apiService';

/** One count of an Allowance in the current period. A limit of null is no cap. */
export interface UsageCount {
  limit: number | null;
  used: number;
  left: number | null;
}

/** What the User has used and has left of the Allowance period holding now. */
export interface AllowanceUsage {
  trial: boolean;
  /** When the period ends: the next reset, or the Trial's end. */
  resetsAt: Date;
  xPosts: UsageCount;
  /** Of the X posts, those containing a link. */
  linkXPosts: UsageCount;
}

export interface Usage {
  /** Null where the Instance sells no Plans or the User isn't Subscribed. */
  allowance: AllowanceUsage | null;
}

interface UsageApi {
  allowance: {
    trial: boolean;
    resets_at: string;
    x_posts: UsageCount;
    link_x_posts: UsageCount;
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
        xPosts: allowance.x_posts,
        linkXPosts: allowance.link_x_posts,
      },
    };
  },
};
