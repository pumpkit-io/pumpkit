import { useEffect, useState } from 'react';

const SHOWN_FOR_MS = 5000;

type Listener = (message: string) => void;
const listeners = new Set<Listener>();

/** Confirms something that finished, at the foot of the screen, through the mounted `Toaster`. */
export function showToast(message: string): void {
  listeners.forEach((listen) => listen(message));
}

/** Where `showToast` messages appear; the signed-in layout mounts one. */
export function Toaster() {
  const [toast, setToast] = useState<{ id: number; message: string } | null>(null);

  useEffect(() => {
    // The id makes the same message shown twice restart its timer.
    const listen: Listener = (message) =>
      setToast((last) => ({ id: (last?.id ?? 0) + 1, message }));
    listeners.add(listen);
    return () => {
      listeners.delete(listen);
    };
  }, []);

  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(null), SHOWN_FOR_MS);
    return () => clearTimeout(timer);
  }, [toast]);

  return (
    <div
      aria-live="polite"
      className="pointer-events-none fixed inset-x-0 bottom-6 z-[60] flex justify-center px-4"
    >
      {toast && (
        <p
          key={toast.id}
          className="pointer-events-auto max-w-md rounded-md border border-border bg-card px-4 py-2.5 font-sans text-sm text-foreground shadow-lg"
        >
          {toast.message}
        </p>
      )}
    </div>
  );
}
