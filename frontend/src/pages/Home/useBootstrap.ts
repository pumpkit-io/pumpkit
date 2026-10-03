import { useEffect, useState, type Dispatch, type SetStateAction } from 'react';
import { userService, type UserProfile } from '@/services/userService';

export function useBootstrap(): {
  profile: UserProfile | null;
  setProfile: Dispatch<SetStateAction<UserProfile | null>>;
} {
  const [profile, setProfile] = useState<UserProfile | null>(null);
  useEffect(() => {
    let cancelled = false;
    userService
      .fetchProfile()
      .then((p) => {
        if (!cancelled) setProfile(p);
      })
      .catch(() => {
        /* UI handles a null profile */
      });
    return () => {
      cancelled = true;
    };
  }, []);
  return { profile, setProfile };
}
