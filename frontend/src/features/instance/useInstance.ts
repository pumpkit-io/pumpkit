import { useContext } from 'react';
import type { Instance } from '@/lib/instance';
import { InstanceContext } from './InstanceProvider';

export function useInstance(): Instance {
  return useContext(InstanceContext);
}
