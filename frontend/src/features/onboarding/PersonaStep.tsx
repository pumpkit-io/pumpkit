import { PositioningPanel } from '@/features/positioning/PositioningPanel';
import { track } from '@/lib/analytics';
import { errorMessage, errorStatus } from '@/services/apiErrors';
import { onboardingService } from '@/services/onboardingService';
import { useOnboarding } from './useOnboarding';

const NOT_CONTINUED = "Couldn't continue. Try again.";

/** Onboarding's last step: write or edit the drafted Positioning, then Continue into Pumpkit. */
export function PersonaStep() {
  const { refresh } = useOnboarding();

  const finish = async (): Promise<string | null> => {
    try {
      await onboardingService.finish();
    } catch (e) {
      if (errorStatus(e) !== 403) return errorMessage(e, NOT_CONTINUED);
      void refresh();
      return null;
    }
    track('onboarding_finished');
    // The gate then sends the finished User to New post. Finishing is idempotent, so a failed
    // check is answered by pressing Continue again.
    return (await refresh()) === undefined ? NOT_CONTINUED : null;
  };

  return (
    <div className="max-w-[560px]">
      <PositioningPanel onContinue={finish} />
    </div>
  );
}
