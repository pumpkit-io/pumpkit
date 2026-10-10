import { CalendarClock, House, type LucideIcon } from 'lucide-react';

/** The pages the sidebar links to, in order; each gets an expanded row and a rail icon. */
export const SIDEBAR_PAGES: { path: string; label: string; icon: LucideIcon }[] = [
  { path: '/home', label: 'Home', icon: House },
  { path: '/scheduled', label: 'Scheduled', icon: CalendarClock },
];
