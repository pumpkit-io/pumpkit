import { createContext, type ReactNode } from 'react';
import { useXConnection } from './useXConnection';

type XConnectionValue = ReturnType<typeof useXConnection>;

export const XConnectionContext = createContext<XConnectionValue | null>(null);

/** One X connection for the panel that manages it and the composer that posts through it. */
export function XConnectionProvider({ children }: { children: ReactNode }) {
  const value = useXConnection();
  return <XConnectionContext.Provider value={value}>{children}</XConnectionContext.Provider>;
}
