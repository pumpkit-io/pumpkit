import { useEffect, type ReactNode } from 'react';
import { useSidebar } from '@/features/sidebar/useSidebar';
import { cn } from '@/lib/utils';

interface ShellProps {
  sidebar: ReactNode;
  sidebarDrawer: ReactNode;
  main: ReactNode;
}

export function Shell({ sidebar, sidebarDrawer, main }: ShellProps) {
  const { collapsed, setMobileOpen } = useSidebar();

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setMobileOpen(false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [setMobileOpen]);

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
