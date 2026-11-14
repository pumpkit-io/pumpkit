import { PositioningPanel } from '@/features/positioning/PositioningPanel';
import { track } from '@/lib/analytics';
import { errorMessage, errorStatus } from '@/services/apiErrors';
import { onboardingService, type NextStep } from '@/services/onboardingService';
import { useOnboarding } from './useOnboarding';

const NOT_CONTINUED = "Couldn't continue. Try again.";

/** True when Onboarding's check answered a step the gate takes the User off this one for. */
function movedOn(next: NextStep | null | undefined): boolean {
  return next !== undefined && next !== 'persona';
}

/** Onboarding's last step: write or edit the drafted Positioning, then Continue into Pumpkit. */
export function PersonaStep() {
  const { refresh } = useOnboarding();

  const finish = async (): Promise<string | null> => {
    try {
      await onboardingService.finish();
    } catch (e) {
      if (errorStatus(e) !== 403) return errorMessage(e, NOT_CONTINUED);
      // A 403 means the check now answers another step, such as the Paywall.
      return movedOn(await refresh()) ? null : NOT_CONTINUED;
    }
    track('onboarding_finished');
    // Finishing is idempotent, so a failed check is answered by pressing Continue again.
    return movedOn(await refresh()) ? null : NOT_CONTINUED;
  };

  return (
    <div className="max-w-[560px]">
      <PositioningPanel onContinue={finish} />
    </div>
  );
}
