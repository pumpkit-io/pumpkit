import { PersonaChip } from '@/features/inspirationAuthors/PersonaChip';
import { PostWriter } from '@/features/posts/PostWriter';
import { Topbar } from '@/features/topbar/Topbar';

/** Rendered inside AppLayout, which holds the shell, the Persona and the Post. */
export function NewPost() {
  return (
    <>
      <Topbar title="New post" actions={<PersonaChip />} />
      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-2xl px-4 py-8 sm:px-6">
          <PostWriter />
        </div>
      </div>
    </>
  );
}
