import { Rows3, Settings, SquarePen, UserRound, type LucideIcon } from 'lucide-react';

/** The pages the sidebar links to, in order. */
export const SIDEBAR_PAGES: { path: string; label: string; icon: LucideIcon }[] = [
  { path: '/new', label: 'New post', icon: SquarePen },
  { path: '/posts', label: 'Posts', icon: Rows3 },
  { path: '/persona', label: 'Persona', icon: UserRound },
  { path: '/settings', label: 'Settings', icon: Settings },
];
