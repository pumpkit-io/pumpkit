/** A sprite sheet's frame list, as animate-pixel-art writes it, at one screen pixel per cell. */
export interface SheetMeta {
  frame_width: number;
  frame_height: number;
  columns: number;
  rows: number;
  frames: { x: number; y: number; ms: number }[];
}

/** Sizes a sheet's frame at `px` screen pixels per cell and shows its frame at (x, y). */
export function spriteStyle(url: string, meta: SheetMeta, x: number, y: number, px: number) {
  return {
    width: meta.frame_width * px,
    height: meta.frame_height * px,
    backgroundImage: `url(${url})`,
    backgroundSize: `${meta.columns * meta.frame_width * px}px ${meta.rows * meta.frame_height * px}px`,
    backgroundPosition: `${-x * px}px ${-y * px}px`,
  };
}
