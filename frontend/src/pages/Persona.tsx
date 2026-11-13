import { InspirationAuthorsPanel } from '@/features/inspirationAuthors/InspirationAuthorsPanel';
import { PositioningPanel } from '@/features/positioning/PositioningPanel';
import { Topbar } from '@/features/topbar/Topbar';

/** Rendered inside AppLayout, which holds the Persona the sidebar and New post read too. */
export function Persona() {
  return (
    <>
      <Topbar title="Persona" />
      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-2xl space-y-12 px-4 py-8 sm:px-6">
          <PositioningPanel />
          <InspirationAuthorsPanel />
        </div>
      </div>
    </>
  );
}
