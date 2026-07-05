/** Sticky (localStorage-persisted) state under `spotfx.builder.v1.*`.
 * Seed rule: if the key has never been written, `seed` (e.g. a server-settings
 * default) initializes it once; afterwards localStorage always wins. */
import { useCallback, useEffect, useRef, useState } from 'react';

const NS = 'spotfx.builder.v1.';

export function readSticky<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(NS + key);
    return raw === null ? fallback : (JSON.parse(raw) as T);
  } catch {
    return fallback;
  }
}

export function writeSticky<T>(key: string, value: T): void {
  try {
    localStorage.setItem(NS + key, JSON.stringify(value));
  } catch {
    /* quota/private mode — non-fatal */
  }
}

export function useSticky<T>(key: string, defaultValue: T, seed?: T | undefined) {
  const [value, setValue] = useState<T>(() => {
    const raw = localStorage.getItem(NS + key);
    if (raw !== null) {
      try {
        return JSON.parse(raw) as T;
      } catch {
        /* fallthrough */
      }
    }
    return seed !== undefined ? seed : defaultValue;
  });

  // Seed arrives async (server settings) — apply once if the key was never written.
  const seeded = useRef(false);
  useEffect(() => {
    if (seed === undefined || seeded.current) return;
    seeded.current = true;
    if (localStorage.getItem(NS + key) === null) setValue(seed);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seed]);

  const set = useCallback(
    (v: T | ((prev: T) => T)) => {
      setValue((prev) => {
        const next = typeof v === 'function' ? (v as (p: T) => T)(prev) : v;
        writeSticky(key, next);
        return next;
      });
    },
    [key],
  );

  return [value, set] as const;
}
