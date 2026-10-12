import { createContext, type ReactNode } from 'react';
import { DEFAULT_INSTANCE, type Instance } from '@/lib/instance';

// Without a provider, as in tests, components see DEFAULT_INSTANCE: the Magic link only,
// with no Plans, Operator details, support address or analytics.
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
