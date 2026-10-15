/** A media query as React state — the generic form of `useIsPhone`, for
 * the places where a layout decision cannot be made in CSS alone because
 * it moves an element between two DOM hosts (the next-event box between
 * the song-timeline row and the bar's second row, components/
 * SongNextBox.tsx). CSS can hide and show; it cannot reparent.
 *
 * Prefer plain CSS whenever the decision IS only about appearance: a
 * JS breakpoint is a second source of truth for a width, and the two can
 * disagree. Every caller here therefore names the SAME query string a
 * tokens.css rule already uses, in one place, so they cannot drift. */
import { useEffect, useState } from 'react';

export default function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => (
    typeof window !== 'undefined' && typeof window.matchMedia === 'function'
      ? window.matchMedia(query).matches
      : false));
  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return undefined;
    const mq = window.matchMedia(query);
    const onChange = () => setMatches(mq.matches);
    setMatches(mq.matches);
    mq.addEventListener('change', onChange);
    return () => mq.removeEventListener('change', onChange);
  }, [query]);
  return matches;
}
