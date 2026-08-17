/** Separates an instant UI response from a delayed server apply — for a
 * control the user cycles rapidly (e.g. tapping through Mode's three
 * states) where every intermediate value reaching the room would spam it,
 * but the BUTTON itself must never feel debounced.
 *
 * Debouncing the button (ignoring taps that land inside the window) reads
 * as sluggish — the opposite of what a spam guard is for. Instead, the
 * caller updates its own display state synchronously on every tap
 * (instant), and calls `schedule(value)` here on every tap too; only the
 * APPLY (the callback) is delayed and re-armed, trailing-edge, so a burst
 * of taps applies exactly once, for whichever value was landed on last. */
import { useEffect, useRef } from 'react';

export function useDebouncedApply<T>(applyFn: (value: T) => void, delayMs = 1000) {
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const applyRef = useRef(applyFn);
  applyRef.current = applyFn;

  const cancel = () => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  };

  const schedule = (value: T) => {
    cancel();
    timerRef.current = setTimeout(() => {
      timerRef.current = null;
      applyRef.current(value);
    }, delayMs);
  };

  useEffect(() => cancel, []);

  const isPending = () => timerRef.current !== null;

  return { schedule, cancel, isPending };
}
