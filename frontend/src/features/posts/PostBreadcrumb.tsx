import { Link } from 'react-router-dom';
import type { PostStatus } from '@/services/postService';
import { STATUS_TAB } from './postStatus';

const CRUMB =
  'text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded-sm';

/** "Posts / {status} / {title}", for the page header's title; the status links to its tab. */
export function PostBreadcrumb({ status, title }: { status: PostStatus; title: string }) {
  const tab = STATUS_TAB[status];
  return (
    <span className="flex min-w-0 items-baseline">
      <Link to="/posts" className={`${CRUMB} shrink-0 font-medium`}>
        Posts
      </Link>
      <span aria-hidden className="whitespace-pre text-muted-foreground/60">
        {' / '}
      </span>
      <Link to={tab.path} className={`${CRUMB} shrink-0 font-medium`}>
        {tab.label}
      </Link>
      <span aria-hidden className="whitespace-pre text-muted-foreground/60">
        {' / '}
      </span>
      <span className="truncate">{title}</span>
    </span>
  );
}
