import { Badge, type BadgeProps } from '@/components/ui/badge';
import { STATUS_LABEL } from '@/features/posts/postStatus';
import type { PostStatus } from '@/services/postService';

const VARIANT: Record<Exclude<PostStatus, 'draft'>, BadgeProps['variant']> = {
  scheduled: 'accent',
  published: 'success',
  failed: 'destructive',
};

/** A Post's status once it has a Scheduled post; `publishing` marks a Scheduled one going out. */
export function StatusBadge({
  status,
  publishing = false,
}: {
  status: Exclude<PostStatus, 'draft'>;
  publishing?: boolean;
}) {
  if (publishing) return <Badge variant="warning">Publishing</Badge>;
  return <Badge variant={VARIANT[status]}>{STATUS_LABEL[status]}</Badge>;
}
