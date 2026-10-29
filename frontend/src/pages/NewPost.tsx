import { PersonaChip } from '@/features/inspirationAuthors/PersonaChip';
import { PostWriter } from '@/features/posts/PostWriter';
import { Topbar } from '@/features/topbar/Topbar';

/** The composer for a Brief; writing a Post opens the Post's page. */
export function NewPost() {
  return (
    <>
      <Topbar title="New post" actions={<PersonaChip />} />
      <div className="flex flex-1 flex-col overflow-y-auto">
        {/* Splitting the free space 2:3 sets the line and composer about 40% down the page. */}
        <div className="min-h-8 flex-[2]" />
        <div className="mx-auto w-full max-w-[42rem] px-4 sm:px-6">
          <PostWriter />
        </div>
        <div className="min-h-8 flex-[3]" />
      </div>
    </>
  );
}
