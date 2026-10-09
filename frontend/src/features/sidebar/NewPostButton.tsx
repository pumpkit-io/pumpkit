import { SquarePen } from 'lucide-react';
import { MOD_LABEL } from '@/lib/shortcuts';
import { SidebarRowButton } from './SidebarRowButton';
import { useNewPost } from './useNewPost';

export function NewPostButton() {
  const { start, disabled } = useNewPost();
  return (
    <div className="mb-1 mt-1">
      <SidebarRowButton
        icon={<SquarePen className="h-5 w-5" />}
        label="New Post"
        disabled={disabled}
        onClick={() => start('sidebar')}
        trailing={
          <kbd
            aria-hidden
            className="hidden font-sans text-xs tracking-wide text-muted-foreground/60 sm:inline"
          >
            {MOD_LABEL}⇧O
          </kbd>
        }
      />
    </div>
  );
}
