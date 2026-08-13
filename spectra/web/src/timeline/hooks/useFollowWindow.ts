/** Zoom window: follow mode tracks the playhead — [now+future−win, now+future] —
 * while manual mode holds absolute bounds. Sticky: follow flag + window/future
 * sizes (seeded from server builder_* settings). The canvas asks getWin() per
 * frame; React consumers re-render only on mode/manual-bound changes. */
import { useCallback, useRef, useState } from 'react';
import { useSticky } from '../../lib/useSticky';

export interface Win {
  startMs: number;
  endMs: number;
}

export function useFollowWindow(opts: {
  getNowMs: () => number | null;
  durationMs: number;
  seedWindowS?: number;
  seedFutureS?: number;
  /** Sticky-key namespace so other pages (Now Playing, Debug) don't share
   * the builder's persisted zoom prefs. Default '' = builder keys. */
  keyPrefix?: string;
}) {
  const { getNowMs, durationMs } = opts;
  const p = opts.keyPrefix ?? '';
  const [follow, setFollow] = useSticky<boolean>(`${p}follow`, true);
  const [windowS, setWindowS] = useSticky<number>(`${p}zoomWindowS`, 30, opts.seedWindowS);
  const [futureS, setFutureS] = useSticky<number>(`${p}futureBufferS`, 10, opts.seedFutureS);
  const [manualWin, setManualWin] = useState<Win | null>(null);

  const stable = useRef({ follow, windowS, futureS, manualWin, durationMs, getNowMs });
  stable.current = { follow, windowS, futureS, manualWin, durationMs, getNowMs };

  const getWin = useCallback((): Win => {
    const s = stable.current;
    const dur = Math.max(1, s.durationMs);
    if (!s.follow && s.manualWin) {
      return clampWin(s.manualWin, dur);
    }
    if (s.follow) {
      const now = s.getNowMs() ?? 0;
      const winMs = s.windowS * 1000;
      const end = now + s.futureS * 1000;
      return clampWin({ startMs: end - winMs, endMs: end }, dur, winMs);
    }
    return { startMs: 0, endMs: dur };
  }, []);

  /** Full Song toggles: if already showing the whole song, shrink back to a
   * default-size window (at the playhead when there is one, else the start). */
  const fullSong = useCallback(() => {
    const s = stable.current;
    const showingFull = !s.follow && s.manualWin === null;
    setFollow(false);
    if (!showingFull) {
      setManualWin(null); // show full song
      return;
    }
    const winMs = s.windowS * 1000;
    const now = s.getNowMs();
    const center = now !== null ? now : winMs / 2;
    setManualWin(clampWin(
      { startMs: center - winMs / 2, endMs: center + winMs / 2 },
      Math.max(1, s.durationMs), winMs,
    ));
  }, [setFollow]);

  /** Enabling follow snaps to the playhead keeping the CURRENT window size —
   * but only when that size is a real zoom. A span covering (nearly) the
   * whole song means "was at full song": zoom back in to the sticky size
   * instead, and never let a song-sized span become the sticky size.
   * Disabling follow freezes the current window in place (manual mode)
   * rather than zooming out to the full song — that's what fullSong is for. */
  const setFollowSnapped = useCallback((on: boolean) => {
    if (!on && stable.current.follow) {
      setManualWin(getWin());
    }
    if (on) {
      const s = stable.current;
      const dur = Math.max(1, s.durationMs);
      const isZoom = (secs: number) => secs * 1000 < dur * 0.8;
      const manualSpanS = !s.follow && s.manualWin
        ? Math.round((s.manualWin.endMs - s.manualWin.startMs) / 1000)
        : null;
      let spanS = manualSpanS !== null && isZoom(manualSpanS) ? manualSpanS : s.windowS;
      if (!isZoom(spanS)) spanS = 30; // sticky size itself was song-sized
      spanS = Math.max(2, spanS);
      setWindowS(spanS);
      setFutureS((f) => Math.min(f, Math.round(spanS / 3)));
      setManualWin(null); // a stale full-song manual window must not linger
    }
    setFollow(on);
  }, [setFollow, setWindowS, setFutureS, getWin]);

  return {
    follow,
    setFollow,
    windowS,
    setWindowS,
    futureS,
    setFutureS,
    manualWin,
    setManualWin,
    fullSong,
    setFollowSnapped,
    getWin,
  };
}

function clampWin(win: Win, durationMs: number, minSpanMs = 1000): Win {
  let { startMs, endMs } = win;
  const span = Math.max(minSpanMs, endMs - startMs);
  if (startMs < 0) {
    startMs = 0;
    endMs = span;
  }
  if (endMs > durationMs) {
    endMs = durationMs;
    startMs = Math.max(0, endMs - span);
  }
  return { startMs, endMs };
}
