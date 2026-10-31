import { apiService } from './apiService';

/** Where the backend sends the signed-in User next; null once Pumpkit is open to them. */
export type NextStep = 'paywall';

export const onboardingService = {
  fetchNextStep: async (): Promise<NextStep | null> => {
    const { data } = await apiService.get<{ next_step: NextStep | null }>('/onboarding');
    return data.next_step;
  },
};
