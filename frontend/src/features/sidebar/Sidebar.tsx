import { useEffect, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { PanelLeft, SquarePen } from 'lucide-react';
import { Brand } from '@/components/brand/Brand';
import { cn } from '@/lib/utils';
import { useSidebar } from './useSidebar';
import { NewPostButton } from './NewPostButton';
import { SIDEBAR_PAGES } from './pages';
import { RailTooltip } from './RailTooltip';
import { SidebarRowButton } from './SidebarRowButton';
import { useNewPost } from './useNewPost';
import { FADE, SLIDE_AND_FADE } from './transitions';
import { UserCard } from './UserCard';

function ToggleButton({ collapsed, onClick }: { collapsed: boolean; onClick: () => void }) {
  const label = collapsed ? 'Open sidebar' : 'Close sidebar';
  return (
    <button
      type="button"
      onClick={onClick}
      className="group relative flex h-10 w-10 items-center justify-center rounded-xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      aria-label={label}
    >
      <span className="flex h-full w-full items-center justify-center rounded-xl bg-transparent text-muted-foreground transition-all duration-150 ease-out group-hover:bg-[var(--hover)] group-hover:text-foreground">
        <PanelLeft className="h-5 w-5" />
      </span>
      <RailTooltip label={label} />
    </button>
  );
}

export function Sidebar({ forceExpanded = false }: { forceExpanded?: boolean } = {}) {
  const { collapsed, toggleCollapsed, setMobileOpen } = useSidebar();
  const newPost = useNewPost();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const goTo = (path: string) => {
    navigate(path);
    setMobileOpen(false);
  };
  const [hovered, setHovered] = useState(false);
  const [toggleFocused, setToggleFocused] = useState(false);
  const collapsedRailRef = useRef<HTMLDivElement>(null);
  const expandedBodyRef = useRef<HTMLDivElement>(null);

  const isExpanded = forceExpanded || !collapsed;
  // On the collapsed rail the toggle takes the logo's place on hover or keyboard focus.
  const brandVisible = isExpanded || (!hovered && !toggleFocused);
  const toggleVisible = isExpanded || hovered || toggleFocused;

  useEffect(() => {
    collapsedRailRef.current?.toggleAttribute('inert', isExpanded);
    expandedBodyRef.current?.toggleAttribute('inert', !isExpanded);
  }, [isExpanded]);

  return (
    <div
      className="flex h-full w-full flex-col bg-card"
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <div className="relative mt-1 h-14 overflow-hidden">
        <div
          className={cn(
            'absolute inset-y-0 left-0 flex items-center',
            SLIDE_AND_FADE,
            isExpanded ? 'pl-3' : 'pl-2',
          )}
          style={{ opacity: brandVisible ? 1 : 0, pointerEvents: brandVisible ? 'auto' : 'none' }}
          aria-hidden={!brandVisible}
        >
          <Brand nameHidden={!isExpanded} />
        </div>
        <div
          className={cn(
            'absolute inset-y-0 right-0 flex items-center',
            SLIDE_AND_FADE,
            // 7px: the aside's 1px border sits inside its 56px, and the rail's icons centre on 28px.
            isExpanded ? 'pr-3' : 'pr-[7px]',
          )}
          style={{ opacity: toggleVisible ? 1 : 0, pointerEvents: toggleVisible ? 'auto' : 'none' }}
          // A click also focuses the toggle; only keyboard focus should keep it over the logo.
          onFocus={(e) => setToggleFocused(e.target.matches(':focus-visible'))}
          onBlur={() => setToggleFocused(false)}
        >
          <ToggleButton collapsed={!isExpanded} onClick={toggleCollapsed} />
        </div>
      </div>

      <div className="relative min-h-0 flex-1">
        <div
          ref={collapsedRailRef}
          className={cn(
            'absolute inset-y-0 left-0 flex w-14 flex-col items-center gap-1 pb-2 pt-1',
            FADE,
          )}
          style={{ opacity: isExpanded ? 0 : 1, pointerEvents: isExpanded ? 'none' : 'auto' }}
        >
          <nav aria-label="Sidebar rail">
            <button
              type="button"
              onClick={() => newPost.start('rail')}
              disabled={newPost.disabled}
              className="group relative inline-flex h-10 w-10 items-center justify-center rounded-xl text-muted-foreground transition-colors hover:bg-[var(--hover)] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50"
              aria-label="New Post"
            >
              <SquarePen className="h-5 w-5" />
              <RailTooltip label="New Post" />
            </button>
            {SIDEBAR_PAGES.map(({ path, label, icon: Icon }) => (
              <button
                key={path}
                type="button"
                onClick={() => goTo(path)}
                aria-current={pathname === path ? 'page' : undefined}
                className="group relative inline-flex h-10 w-10 items-center justify-center rounded-xl text-muted-foreground transition-colors hover:bg-[var(--hover)] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring aria-[current=page]:bg-[var(--hover)] aria-[current=page]:text-foreground"
                aria-label={label}
              >
                <Icon className="h-5 w-5" />
                <RailTooltip label={label} />
              </button>
            ))}
          </nav>
        </div>

        <div
          ref={expandedBodyRef}
          className={cn('absolute inset-0 flex flex-col', FADE)}
          style={{ opacity: isExpanded ? 1 : 0, pointerEvents: isExpanded ? 'auto' : 'none' }}
        >
          <nav className="flex-1" aria-label="Main">
            <NewPostButton />
            {SIDEBAR_PAGES.map(({ path, label, icon: Icon }) => (
              <SidebarRowButton
                key={path}
                icon={<Icon className="h-5 w-5" />}
                label={label}
                onClick={() => goTo(path)}
                aria-current={pathname === path ? 'page' : undefined}
                className="aria-[current=page]:bg-[var(--hover)]"
              />
            ))}
          </nav>
        </div>
      </div>

      <UserCard expanded={isExpanded} />
    </div>
  );
}
