import { createContext, useContext, useMemo, type ReactNode } from 'react';
import type { UserProfile } from '@/services/userService';

type ProfileSetter = (next: UserProfile | null) => void;

interface ProfileContextValue {
  profile: UserProfile | null;
  setProfile: ProfileSetter;
}

const ProfileContext = createContext<ProfileContextValue | null>(null);

export function ProfileProvider({
  value,
  setValue,
  children,
}: {
  value: UserProfile | null;
  setValue: ProfileSetter;
  children: ReactNode;
}) {
  const ctx = useMemo<ProfileContextValue>(
    () => ({ profile: value, setProfile: setValue }),
    [value, setValue],
  );
  return <ProfileContext.Provider value={ctx}>{children}</ProfileContext.Provider>;
}

export function useProfile(): UserProfile | null {
  return useContext(ProfileContext)?.profile ?? null;
}

export function useProfileMutator(): ProfileSetter {
  const ctx = useContext(ProfileContext);
  if (!ctx) {
    throw new Error('useProfileMutator must be used within a ProfileProvider');
  }
  return ctx.setProfile;
}
