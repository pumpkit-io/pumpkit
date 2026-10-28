import { cn } from '@/lib/utils';
import { DEFAULT_INSTANCE } from '@/lib/instance';
import { useInstance } from '@/features/instance/useInstance';
import { useTheme } from '@/features/theme/useTheme';
import mascot from '@/assets/brand/mascot.svg';
import wordmarkLight from '@/assets/brand/wordmark-light.svg';
import wordmarkDark from '@/assets/brand/wordmark-dark.svg';

interface BrandProps {
  className?: string;
  showName?: boolean;
  /** Fades the name out but keeps its place, so a sidebar closing doesn't make it pop. */
  nameHidden?: boolean;
  size?: 'sm' | 'md';
}

/**
 * The mascot and the name. The wordmark SVGs spell "pumpkit", so an Instance with its own
 * app name shows that name as text. Replace the SVGs in src/assets/brand/ with your own.
 */
export function Brand({ className, showName = true, nameHidden = false, size = 'md' }: BrandProps) {
  const { resolved } = useTheme();
  const { app_name } = useInstance();
  const nameClass = cn(
    'select-none transition-opacity duration-150 ease-out motion-reduce:transition-none',
    nameHidden && 'opacity-0',
  );
  return (
    <span className={cn('flex items-center gap-2', className)}>
      <img
        src={mascot}
        alt=""
        className={cn('w-auto shrink-0 select-none', size === 'sm' ? 'h-8' : 'h-10')}
        draggable={false}
      />
      {showName &&
        (app_name === DEFAULT_INSTANCE.app_name ? (
          <img
            src={resolved === 'dark' ? wordmarkDark : wordmarkLight}
            alt={nameHidden ? '' : app_name}
            aria-hidden={nameHidden || undefined}
            className={cn('w-auto', size === 'sm' ? 'h-[19px]' : 'h-6', nameClass)}
            draggable={false}
          />
        ) : (
          <span
            aria-hidden={nameHidden || undefined}
            className={cn(
              'font-sans text-lg font-bold leading-none tracking-[-0.03em] text-foreground',
              nameClass,
            )}
          >
            {app_name}
          </span>
        ))}
    </span>
  );
}
