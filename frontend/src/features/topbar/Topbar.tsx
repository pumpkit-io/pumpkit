import { Menu } from 'lucide-react';
import { useSidebar } from '@/features/sidebar/useSidebar';

export function Topbar({ title }: { title: string }) {
  const { setMobileOpen } = useSidebar();
  return (
    <header className="sticky top-0 z-20 flex h-14 items-center gap-3 border-b border-border bg-background px-5">
      <button
        type="button"
        onClick={() => setMobileOpen(true)}
        className="-ml-3 inline-flex h-11 w-11 items-center justify-center rounded-md text-muted-foreground hover:bg-muted md:hidden"
        aria-label="Open sidebar"
      >
        <Menu className="h-4 w-4" />
      </button>
      <div className="font-sans text-sm text-foreground/80">{title}</div>
    </header>
  );
}
