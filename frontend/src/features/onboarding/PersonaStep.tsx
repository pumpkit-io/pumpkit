import { useState } from 'react';
import { ErrorBanner } from '@/components/ErrorBanner';
import { Button } from '@/components/ui/button';
import { InspirationAuthorsPanel } from '@/features/inspirationAuthors/InspirationAuthorsPanel';
import { InspirationAuthorsProvider } from '@/features/inspirationAuthors/InspirationAuthorsProvider';
import { useInspirationAuthorsContext } from '@/features/inspirationAuthors/useInspirationAuthorsContext';
import { track } from '@/lib/analytics';
import { errorMessage, errorStatus } from '@/services/apiErrors';
import { onboardingService } from '@/services/onboardingService';
import { useOnboarding } from './useOnboarding';

function ContinueButton({ onError }: { onError: (message: string | null) => void }) {
  const { authors, adding } = useInspirationAuthorsContext();
  const { refresh } = useOnboarding();
  const [finishing, setFinishing] = useState(false);
  const ready = (authors?.length ?? 0) > 0 && adding === null;

  const finish = async () => {
    onError(null);
    setFinishing(true);
    try {
      await onboardingService.finish();
    } catch (e) {
      setFinishing(false);
      if (errorStatus(e) === 403) void refresh();
      else onError(errorMessage(e, "Couldn't continue. Try again."));
      return;
    }
    track('onboarding_finished');
    // The gate then sends the finished User to New post. Finishing is idempotent, so a failed
    // check is answered by pressing Continue again.
    if ((await refresh()) === undefined) {
      setFinishing(false);
      onError("Couldn't continue. Try again.");
    }
  };

  return (
    <Button type="button" disabled={!ready || finishing} onClick={() => void finish()}>
      {finishing ? 'Continuing…' : 'Continue'}
    </Button>
  );
}

/** Onboarding's last step: choose a Persona, then Continue into Pumpkit. */
export function PersonaStep() {
  const [error, setError] = useState<string | null>(null);

  return (
    <InspirationAuthorsProvider>
      <div className="max-w-[560px] space-y-4">
        <InspirationAuthorsPanel
          step={{
            title: 'Choose up to three authors to write like',
            action: <ContinueButton onError={setError} />,
          }}
        />
        {error && <ErrorBanner message={error} />}
      </div>
    </InspirationAuthorsProvider>
  );
}
