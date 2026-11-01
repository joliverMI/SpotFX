/** Forces a re-render every `intervalMs` — used only by components that
 * display a continuously-advancing value (the Party screen's progress
 * bar/clock) computed from interpolation, not from a new feed message.
 * Returns nothing; callers read the clock themselves at render time. */
import { useEffect, useState } from 'react';

export function useTick(intervalMs: number): number {
  const [, setN] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setN((n) => n + 1), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return Date.now();
}
