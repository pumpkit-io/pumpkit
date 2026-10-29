import { useCallback, type ReactNode } from 'react';
import { useNewPost } from '@/features/sidebar/useNewPost';
import { useSidebar } from '@/features/sidebar/useSidebar';
import { useShortcuts } from '@/lib/shortcuts';

interface ShellProps {
  /** Above every page's header, such as the Reconnect X banner; renders nothing when null. */
  banner: ReactNode;
  sidebar: ReactNode;
  sidebarDrawer: ReactNode;
  main: ReactNode;
}

/** The fixed sidebar from `md` up, a drawer below it, and the page beside it on a raised panel. */
export function Shell({ banner, sidebar, sidebarDrawer, main }: ShellProps) {
  const { setMobileOpen } = useSidebar();
  const { start: startNewPost } = useNewPost();

  useShortcuts({
    onNewPost: useCallback(() => startNewPost('shortcut'), [startNewPost]),
    onEscape: useCallback(() => setMobileOpen(false), [setMobileOpen]),
  });

  return (
    <div className="flex h-[100dvh] w-full overflow-hidden bg-background text-foreground">
      <aside className="hidden w-60 shrink-0 md:flex">{sidebar}</aside>
      {sidebarDrawer}
      <main className="relative flex min-w-0 flex-1 flex-col overflow-hidden bg-card md:my-2 md:mr-2 md:rounded-xl md:border md:border-border md:shadow-panel">
        {banner}
        {main}
      </main>
    </div>
  );
}
