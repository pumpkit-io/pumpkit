import { useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { track } from '@/lib/analytics';

/** The Choose a Plan card's id on Settings, where every prompt to subscribe leads. */
export const CHOOSE_PLAN_ID = 'choose-a-plan';
export const CHOOSE_PLAN_PATH = `/settings#${CHOOSE_PLAN_ID}`;

/** Records which prompt sent the User to Choose a Plan; `source` names the prompt. */
export function trackChoosePlan(source: string) {
  track('billing_choose_plan_opened', { source });
}

/** Goes to Choose a Plan from code, such as after a write was refused with a 403. */
export function useGoToChoosePlan() {
  const navigate = useNavigate();
  return useCallback(
    (source: string) => {
      trackChoosePlan(source);
      navigate(CHOOSE_PLAN_PATH);
    },
    [navigate],
  );
}
