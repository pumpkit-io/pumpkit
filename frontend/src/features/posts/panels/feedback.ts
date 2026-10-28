import type { Format } from '@/services/postService';

/** What the Feedback bar needs from `usePost`, for the Draft and Failed panels. */
export interface FeedbackSending {
  isWriting: boolean;
  error: string | null;
  notice: string | null;
  onSend: (feedback: string, format: Format) => Promise<boolean>;
}
