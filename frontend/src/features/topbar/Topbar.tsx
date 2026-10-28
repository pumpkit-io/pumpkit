import type { ReactNode } from 'react';
import { Menu } from 'lucide-react';
import { useSidebar } from '@/features/sidebar/useSidebar';

/**
 * The page header: the page's title (or a breadcrumb, passed as `title`) on the left and the
 * page's own controls in `actions` on the right. On a phone it also opens the sidebar drawer.
 */
export function Topbar({ title, actions }: { title: ReactNode; actions?: ReactNode }) {
  const { setMobileOpen } = useSidebar();
  return (
    <header className="sticky top-0 z-20 flex h-14 shrink-0 items-center gap-3 border-b border-border bg-background px-4 sm:px-6">
      <button
        type="button"
        onClick={() => setMobileOpen(true)}
        className="-ml-2 inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring md:hidden"
        aria-label="Open sidebar"
      >
        <Menu className="h-5 w-5" aria-hidden />
      </button>
      <h1 className="min-w-0 truncate font-sans text-base font-semibold text-foreground">
        {title}
      </h1>
      {actions && <div className="ml-auto flex min-w-0 items-center gap-2">{actions}</div>}
    </header>
  );
}
