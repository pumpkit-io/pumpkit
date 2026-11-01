import { useCallback, useEffect, useRef, useState } from 'react';
import costumeChangeSheet from '@/assets/mascot/costume_change-sheet.png';
import costumeChange from '@/assets/mascot/costume_change-sheet.json';
import detectiveSheet from '@/assets/mascot/detective-sheet.png';
import detective from '@/assets/mascot/detective-sheet.json';
import dozeOffSheet from '@/assets/mascot/doze_off-sheet.png';
import dozeOff from '@/assets/mascot/doze_off-sheet.json';
import tadaSheet from '@/assets/mascot/tada-sheet.png';
import tada from '@/assets/mascot/tada-sheet.json';
import { REDUCED_MOTION, useMediaQuery } from '@/lib/useMediaQuery';
import { cn } from '@/lib/utils';

/** A sprite sheet's frame list, as animate-pixel-art writes it, at one screen pixel per cell. */
interface SheetMeta {
  frame_width: number;
  frame_height: number;
  columns: number;
  rows: number;
  frames: { x: number; y: number; ms: number }[];
}

const ANIMATIONS = {
  costume_change: { url: costumeChangeSheet, meta: costumeChange },
  tada: { url: tadaSheet, meta: tada },
  detective: { url: detectiveSheet, meta: detective },
  doze_off: { url: dozeOffSheet, meta: dozeOff },
} satisfies Record<string, { url: string; meta: SheetMeta }>;

export type MascotAnimation = keyof typeof ANIMATIONS;

const MEDIUM = '(min-width: 768px)';

interface MascotProps {
  animation: MascotAnimation;
  /** Plays once on entering the view, after it has stayed in view this long. Off when null. */
  playInViewAfterMs?: number | null;
  /**
   * Rests on the last frame once played, as `doze_off` stays asleep. Hovering then shows the first
   * frame, and leaving plays it again after `playInViewAfterMs`.
   */
  restOnLastFrame?: boolean;
  /** Each change after the first render plays the animation once. */
  trigger?: number;
  /** Whole screen pixels per cell below and from the `md` breakpoint. */
  scale?: number;
  mdScale?: number;
  className?: string;
}

/**
 * The pumpkin mascot: plays its animation once, then rests on the first frame. Hovering replays
 * it, and under reduced motion it only ever shows the first frame.
 */
export function Mascot({
  animation,
  playInViewAfterMs = 0,
  restOnLastFrame = false,
  trigger = 0,
  scale = 2,
  mdScale = 3,
  className,
}: MascotProps) {
  const { url, meta } = ANIMATIONS[animation];
  const reducedMotion = useMediaQuery(REDUCED_MOTION);
  const medium = useMediaQuery(MEDIUM);
  const [frame, setFrame] = useState<number | null>(null);
  const [onLastFrame, setOnLastFrame] = useState(false);
  const ref = useRef<HTMLDivElement | null>(null);
  const hoveredRef = useRef(false);
  const replayTimerRef = useRef<number | undefined>(undefined);

  const play = useCallback(() => {
    if (reducedMotion || (restOnLastFrame && hoveredRef.current)) return;
    setOnLastFrame(false);
    setFrame((current) => current ?? 0);
  }, [reducedMotion, restOnLastFrame]);

  useEffect(() => {
    if (frame === null) return;
    const timer = window.setTimeout(() => {
      if (frame + 1 < meta.frames.length) {
        setFrame(frame + 1);
      } else {
        setFrame(null);
        setOnLastFrame(restOnLastFrame);
      }
    }, meta.frames[frame].ms);
    return () => window.clearTimeout(timer);
  }, [frame, meta, restOnLastFrame]);

  useEffect(() => {
    if (!reducedMotion) return;
    setFrame(null);
    setOnLastFrame(false);
  }, [reducedMotion]);

  useEffect(() => () => window.clearTimeout(replayTimerRef.current), []);

  const onMouseEnter = () => {
    hoveredRef.current = true;
    if (!restOnLastFrame) {
      play();
      return;
    }
    window.clearTimeout(replayTimerRef.current);
    setFrame(null);
    setOnLastFrame(false);
  };

  const onMouseLeave = () => {
    hoveredRef.current = false;
    if (!restOnLastFrame) return;
    window.clearTimeout(replayTimerRef.current);
    replayTimerRef.current = window.setTimeout(() => playRef.current(), playInViewAfterMs ?? 0);
  };

  const playRef = useRef(play);
  playRef.current = play;

  const firstTrigger = useRef(trigger);
  useEffect(() => {
    if (trigger !== firstTrigger.current) playRef.current();
  }, [trigger]);

  useEffect(() => {
    const node = ref.current;
    if (playInViewAfterMs === null || !node) return;
    let timer: number | undefined;
    let observer: IntersectionObserver | undefined;
    const startTimer = () => {
      timer = window.setTimeout(() => {
        playRef.current();
        observer?.disconnect();
      }, playInViewAfterMs);
    };
    if (typeof IntersectionObserver === 'undefined') {
      startTimer();
    } else {
      // Leaving the view before the wait is over starts the wait again next time.
      observer = new IntersectionObserver(
        (entries) => {
          window.clearTimeout(timer);
          if (entries[entries.length - 1].isIntersecting) startTimer();
        },
        { threshold: 0.5 },
      );
      observer.observe(node);
    }
    return () => {
      window.clearTimeout(timer);
      observer?.disconnect();
    };
  }, [playInViewAfterMs]);

  const px = medium ? mdScale : scale;
  const { x, y } = meta.frames[frame ?? (onLastFrame ? meta.frames.length - 1 : 0)];

  return (
    <div
      ref={ref}
      aria-hidden="true"
      data-mascot={animation}
      data-state={frame !== null ? 'playing' : onLastFrame ? 'rested' : 'still'}
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
      className={cn('shrink-0 bg-no-repeat [image-rendering:pixelated]', className)}
      style={{
        width: meta.frame_width * px,
        height: meta.frame_height * px,
        backgroundImage: `url(${url})`,
        backgroundSize: `${meta.columns * meta.frame_width * px}px ${meta.rows * meta.frame_height * px}px`,
        backgroundPosition: `${-x * px}px ${-y * px}px`,
      }}
    />
  );
}
