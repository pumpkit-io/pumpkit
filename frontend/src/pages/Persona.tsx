import { PositioningPanel } from '@/features/positioning/PositioningPanel';
import { Topbar } from '@/features/topbar/Topbar';

/** The Persona is the User's Positioning (ADR 0024). The Inspiration authors panel is inactive. */
export function Persona() {
  return (
    <>
      <Topbar title="Persona" />
      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-2xl space-y-12 px-4 py-8 sm:px-6">
          <PositioningPanel />
        </div>
      </div>
    </>
  );
}
