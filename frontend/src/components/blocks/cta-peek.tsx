import { useEffect, useState, type CSSProperties, type ReactNode } from 'react';
import { spriteStyle, type SheetMeta } from '@/components/blocks/sprite-sheet';
import popUpPeekSheet from '@/assets/mascot/pop_up_peek_paired-sheet.png';
import popUpPeek from '@/assets/mascot/pop_up_peek_paired-sheet.json';
import wallPeekSheet from '@/assets/mascot/wall_peek_paired-sheet.png';
import wallPeek from '@/assets/mascot/wall_peek_paired-sheet.json';
import { REDUCED_MOTION, useMediaQuery } from '@/lib/useMediaQuery';
import { cn } from '@/lib/utils';

const PX = 2;

// The pair shares one loop length, so one clock makes them take turns.
const LOOP_MS = wallPeek.loop_ms;

function frameStarts(meta: SheetMeta): number[] {
  let start = 0;
  return meta.frames.map((frame) => {
    const at = start;
    start += frame.ms;
    return at;
  });
}

const WALL_STARTS = frameStarts(wallPeek);
const POP_STARTS = frameStarts(popUpPeek);

function frameAt(starts: number[], ms: number): number {
  let index = 0;
  while (index + 1 < starts.length && starts[index + 1] <= ms) index++;
  return index;
}

const CHANGES = [...new Set([...WALL_STARTS, ...POP_STARTS, LOOP_MS])].sort((a, b) => a - b);

function nextChange(ms: number): number {
  return CHANGES.find((change) => change > ms)! - ms;
}

type PeekName = 'wall' | 'pop-up';

function Sprite({
  name,
  url,
  meta,
  frame,
  className,
  style,
}: {
  name: PeekName;
  url: string;
  meta: SheetMeta;
  frame: number;
  className: string;
  style: CSSProperties;
}) {
  const { x, y } = meta.frames[frame];
  // The first and last frames are the empty waits around the peek.
  const peeking = frame > 0 && frame < meta.frames.length - 1;
  return (
    <div
      aria-hidden="true"
      data-peek={name}
      data-state={peeking ? 'peeking' : 'hidden'}
      className={cn(
        'pointer-events-none absolute bg-no-repeat [image-rendering:pixelated]',
        className,
      )}
      style={{ ...style, ...spriteStyle(url, meta, x, y, PX) }}
    />
  );
}

/**
 * The mascot takes turns peeking out from behind `children`: out of its right edge, then out of
 * its top edge. Under reduced motion it rests peeking over the top.
 */
export function CtaPeek({ children }: { children: ReactNode }) {
  const reducedMotion = useMediaQuery(REDUCED_MOTION);
  const [ms, setMs] = useState(0);

  useEffect(() => {
    if (reducedMotion) return;
    const start = Date.now();
    let timer: number | undefined;
    const tick = () => {
      const now = (Date.now() - start) % LOOP_MS;
      setMs(now);
      timer = window.setTimeout(tick, nextChange(now));
    };
    tick();
    return () => window.clearTimeout(timer);
  }, [reducedMotion]);

  const wallFrame = reducedMotion ? 0 : frameAt(WALL_STARTS, ms);
  const popFrame = reducedMotion ? popUpPeek.still : frameAt(POP_STARTS, ms);

  // The wall peek's last row is empty, so dropping it one cell lines its feet up with the button's
  // bottom. Two cells tucked behind the button keep it hidden while the pressed button shrinks.
  return (
    <div className="relative isolate">
      <Sprite
        name="wall"
        url={wallPeekSheet}
        meta={wallPeek}
        frame={wallFrame}
        className="left-full"
        style={{ bottom: -PX, marginLeft: -2 * PX }}
      />
      <Sprite
        name="pop-up"
        url={popUpPeekSheet}
        meta={popUpPeek}
        frame={popFrame}
        className="bottom-full left-1/2 -translate-x-1/2"
        style={{ marginBottom: -PX }}
      />
      <div className="relative z-10">{children}</div>
    </div>
  );
}
