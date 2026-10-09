import { useEffect, useRef, useState } from 'react';
import { PanelLeft, SquarePen } from 'lucide-react';
import { Brand } from '@/components/brand/Brand';
import { useProfile } from '@/pages/Home/ProfileContext';
import { cn } from '@/lib/utils';
import { useSidebar } from './useSidebar';
import { NewPostButton } from './NewPostButton';
import { RailTooltip } from './RailTooltip';
import { useNewPost } from './useNewPost';
import { UserCard } from './UserCard';
import { UserMenu } from './UserMenu';

function initials(name: string): string {
  const parts = name.trim().split(/\s+/);
  const first = parts[0]?.[0] ?? '';
  const last = parts.length > 1 ? (parts[parts.length - 1]?.[0] ?? '') : '';
  return (first + last).toUpperCase() || '•';
}

// CSS transitions, not framer-motion: its hardware-accelerated opacity fade shows the old value for a frame when it ends.
const FADE = 'transition-opacity duration-150 ease-out motion-reduce:transition-none';
// Padding slides with the aside's 200ms width so the logo and toggle never jump.
const SLIDE_AND_FADE =
  '[transition:opacity_150ms_ease-out,padding_200ms] motion-reduce:[transition:none]';

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
  const { collapsed, toggleCollapsed } = useSidebar();
  const profile = useProfile();
  const newPost = useNewPost();
  const [hovered, setHovered] = useState(false);
  const [toggleFocused, setToggleFocused] = useState(false);
  const collapsedRailRef = useRef<HTMLDivElement>(null);
  const expandedBodyRef = useRef<HTMLDivElement>(null);

  const isExpanded = forceExpanded || !collapsed;
  const display = profile
    ? [profile.firstName, profile.lastName].filter(Boolean).join(' ') || profile.email
    : '•';
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
            isExpanded ? 'pl-3' : 'pl-1',
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
            isExpanded ? 'pr-3' : 'pr-1',
          )}
          style={{ opacity: toggleVisible ? 1 : 0, pointerEvents: toggleVisible ? 'auto' : 'none' }}
          onFocus={() => setToggleFocused(true)}
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
          </nav>
          <div className="mt-auto">
            <UserMenu
              trigger={
                <button
                  type="button"
                  aria-label="User menu"
                  className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-muted text-xs text-foreground hover:bg-muted/80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  {initials(display)}
                </button>
              }
            />
          </div>
        </div>

        <div
          ref={expandedBodyRef}
          className={cn('absolute inset-0 flex flex-col', FADE)}
          style={{ opacity: isExpanded ? 1 : 0, pointerEvents: isExpanded ? 'auto' : 'none' }}
        >
          <nav className="flex-1" aria-label="Main">
            <NewPostButton />
          </nav>
          <UserCard />
        </div>
      </div>
    </div>
  );
}
