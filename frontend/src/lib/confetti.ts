import confetti from 'canvas-confetti';

/**
 * Radial burst from the centre of `anchor` to draw the eye there; centre-screen if it is unavailable.
 * No-ops under prefers-reduced-motion.
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

  // Some browser extensions block canvas rendering, which throws inside the rAF callback.
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
      // Canvas blocked; see above.
    }
  }, 220);
}
