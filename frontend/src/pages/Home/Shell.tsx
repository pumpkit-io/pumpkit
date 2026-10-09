import { useCallback, type ReactNode } from 'react';
import { useNewPost } from '@/features/sidebar/useNewPost';
import { useSidebar } from '@/features/sidebar/useSidebar';
import { useShortcuts } from '@/lib/shortcuts';
import { cn } from '@/lib/utils';

interface ShellProps {
  sidebar: ReactNode;
  sidebarDrawer: ReactNode;
  main: ReactNode;
}

export function Shell({ sidebar, sidebarDrawer, main }: ShellProps) {
  const { collapsed, setMobileOpen } = useSidebar();
  const { start: startNewPost } = useNewPost();

  useShortcuts({
    onNewPost: useCallback(() => startNewPost('shortcut'), [startNewPost]),
    onEscape: useCallback(() => setMobileOpen(false), [setMobileOpen]),
  });

  return (
    <div className="flex h-[100dvh] w-full overflow-hidden bg-background text-foreground">
      <aside
        className={cn(
          'hidden shrink-0 overflow-hidden border-r border-border transition-[width] duration-200 motion-reduce:transition-none md:flex',
          collapsed ? 'w-14' : 'w-72',
        )}
      >
        {sidebar}
      </aside>
      {sidebarDrawer}
      <main className="relative flex min-w-0 flex-1 flex-col">{main}</main>
    </div>
  );
}
