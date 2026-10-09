import { cn } from '@/lib/utils';
import { APP_NAME } from '@/lib/app';
import { useTheme } from '@/features/theme/useTheme';
import logoLight from '@/assets/brand/logo-light.svg';
import logoDark from '@/assets/brand/logo-dark.svg';

interface BrandProps {
  className?: string;
  showName?: boolean;
  /** Fades the name out but keeps its place, so a sidebar closing doesn't make it pop. */
  nameHidden?: boolean;
  size?: 'sm' | 'md';
}

/** Replace the SVGs in src/assets/brand/ with your own. */
export function Brand({ className, showName = true, nameHidden = false, size = 'md' }: BrandProps) {
  const { resolved } = useTheme();
  const src = resolved === 'dark' ? logoDark : logoLight;
  return (
    <span className={cn('flex items-center gap-2', className)}>
      <img
        src={src}
        alt=""
        className={cn('select-none rounded-lg', size === 'sm' ? 'h-8 w-8' : 'h-10 w-10')}
        draggable={false}
      />
      {showName && (
        <span
          aria-hidden={nameHidden || undefined}
          className={cn(
            'font-wordmark text-lg font-semibold leading-none tracking-[-0.02em] text-foreground',
            'transition-opacity duration-150 ease-out motion-reduce:transition-none',
            nameHidden && 'opacity-0',
          )}
        >
          {APP_NAME}
        </span>
      )}
    </span>
  );
}
