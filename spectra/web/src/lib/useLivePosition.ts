/** Interpolates a polled track position into a smooth, tenth-of-a-second
 * clock between `useEngineStatus`'s 3000ms polls (his words: the timer
 * "needs to be tracking the actual time in the song down to the 10th of a
 * second", not the raw Spotify-pull value it showed before).
 *
 * `bridge.track_position_ms()` (spectra/services/bridge.py) already
 * interpolates server-side up to the moment each /engine/status request is
 * handled, so every poll's `position_ms` is a fresh anchor, not a stale
 * broadcast — this hook just keeps advancing it client-side between polls
 * and re-anchors the instant a fresh one arrives. That re-anchor is also
 * what makes pause/seek/track-change self-correct within one poll interval
 * instead of drifting: a pause shows up as `is_playing: false` (advancement
 * stops dead, never counts through it), and a seek or track change shows up
 * as a jump in the polled value (the next tick snaps straight to it, no
 * special-casing needed). */
import { useEffect, useRef, useState } from 'react';

interface Track {
  position_ms: number | null;
  is_playing: boolean | null;
}

interface Anchor {
  positionMs: number;
  isPlaying: boolean;
  clientMs: number;
}

export function useLivePosition(track: Track | null | undefined): number | null {
  const anchorRef = useRef<Anchor | null>(null);
  const [, tick] = useState(0);

  const polledPos = track?.position_ms ?? null;
  const isPlaying = !!track?.is_playing;

  useEffect(() => {
    anchorRef.current = polledPos == null
      ? null
      : { positionMs: polledPos, isPlaying, clientMs: Date.now() };
    tick((n) => n + 1);
  }, [polledPos, isPlaying]);

  useEffect(() => {
    if (!isPlaying || polledPos == null) return undefined;
    const id = setInterval(() => tick((n) => n + 1), 100);
    return () => clearInterval(id);
  }, [isPlaying, polledPos]);

  const anchor = anchorRef.current;
  if (!anchor) return null;
  const elapsed = anchor.isPlaying ? Date.now() - anchor.clientMs : 0;
  return Math.max(0, anchor.positionMs + elapsed);
}
