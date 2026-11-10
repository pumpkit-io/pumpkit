import { apiService } from './apiService';

/** Where the backend sends the signed-in User next; null once Pumpkit is open to them. */
export type NextStep = 'paywall' | 'persona';

export const onboardingService = {
  fetchNextStep: async (): Promise<NextStep | null> => {
    const { data } = await apiService.get<{ next_step: NextStep | null }>('/onboarding');
    return data.next_step;
  },

  /** Records that the User finished Onboarding; refused while the Persona is empty. */
  finish: async (): Promise<void> => {
    await apiService.post('/onboarding/finish');
  },
};
