import confetti from 'canvas-confetti';

/**
 * Fire a celebratory confetti burst anchored at the centre of `anchor`.
 * The burst is radial (spread: 360) so it visibly emanates from that point,
 * directing the user's gaze. Falls back to a centre-screen burst if the
 * anchor is unavailable. No-ops under prefers-reduced-motion.
 */
export function fireSuccessConfetti(anchor: HTMLElement | null): void {
  if (typeof window === 'undefined') return;
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

  let origin: { x: number; y: number } = { x: 0.5, y: 0.6 };
  if (anchor) {
    const rect = anchor.getBoundingClientRect();
    if (rect.width > 0 && rect.height > 0) {
      origin = {
        x: (rect.left + rect.width / 2) / window.innerWidth,
        y: (rect.top + rect.height / 2) / window.innerHeight,
      };
    }
  }

  // Tight radial pop centred exactly on the anchor.
  // Wrapped in try/catch because some browser extensions block canvas
  // rendering, which would throw inside our rAF callback otherwise.
  try {
    confetti({
      particleCount: 70,
      spread: 360,
      startVelocity: 28,
      scalar: 0.85,
      ticks: 140,
      origin,
    });
  } catch {
    return;
  }
  // Smaller follow-up so the eye lingers on the spot.
  window.setTimeout(() => {
    try {
      confetti({
        particleCount: 35,
        spread: 360,
        startVelocity: 18,
        scalar: 0.7,
        ticks: 120,
        origin,
      });
    } catch {
      // Same rationale — silent fall-through.
    }
  }, 220);
}
