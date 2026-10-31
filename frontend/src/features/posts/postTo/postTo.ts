import type { CreateOutcome } from '@/features/scheduledPosts/useCreateScheduledPost';
import type { AllowanceUsedUp } from '@/services/apiErrors';
import type { Destination } from '@/services/scheduledPostService';

/** Where and when the User sends the Post, as the dialog's Where and When hold them. */
export interface PostToChoice {
  destination: Destination;
  when: { postNow: true } | { postNow: false; publishAt: string };
}

/**
 * What the dialog sends through: creating a Scheduled post on a Draft, or patching the Failed one
 * on a Failed Post. A refusal sets `error`, or `allowanceUsedUp` when the X posts or link posts
 * left don't cover it; `notSubscribed` sends the User to Choose a Plan.
 */
export interface PostToSender {
  sending: boolean;
  error: string | null;
  allowanceUsedUp: AllowanceUsedUp | null;
  send: (choice: PostToChoice) => Promise<CreateOutcome>;
}

/** The `source` of `billing_choose_plan_opened` from "Post to…". */
export const POST_TO_BILLING_SOURCE = 'post_to';
