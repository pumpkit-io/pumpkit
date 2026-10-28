import { createContext, useMemo, useState, type ReactNode } from 'react';

interface SidebarContextValue {
  mobileOpen: boolean;
  setMobileOpen: (v: boolean) => void;
}

export const SidebarContext = createContext<SidebarContextValue | null>(null);

/** Whether the phone drawer is open; from `md` up the sidebar is always on screen. */
export function SidebarProvider({ children }: { children: ReactNode }) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const value = useMemo(() => ({ mobileOpen, setMobileOpen }), [mobileOpen]);
  return <SidebarContext.Provider value={value}>{children}</SidebarContext.Provider>;
}
