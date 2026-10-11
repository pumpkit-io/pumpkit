import { createContext, type ReactNode } from 'react';
import { DEFAULT_INSTANCE, type Instance } from '@/lib/instance';

// Defaults to today's Instance so components rendered without a provider, as in tests, still work.
export const InstanceContext = createContext<Instance>(DEFAULT_INSTANCE);

/** Holds the Instance response that main.tsx fetched before rendering. */
export function InstanceProvider({
  instance,
  children,
}: {
  instance: Instance;
  children: ReactNode;
}) {
  return <InstanceContext.Provider value={instance}>{children}</InstanceContext.Provider>;
}
