/** Forces a re-render every `intervalMs` — used only by components that
 * display a continuously-advancing value (the Party screen's progress
 * bar/clock) computed from interpolation, not from a new feed message.
 * The returned timestamp is unused today (every caller reads the clock
 * itself, via feed.ts's `nowMs()`, at render time) — it exists only so
 * a future caller isn't forced into a second `Date.now()` call. */
import { useEffect, useState } from 'react';

export function useTick(intervalMs: number): number {
  const [, setN] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setN((n) => n + 1), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return Date.now();
}
