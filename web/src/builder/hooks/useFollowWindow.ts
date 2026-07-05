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
}) {
  const { getNowMs, durationMs } = opts;
  const [follow, setFollow] = useSticky<boolean>('follow', true);
  const [windowS, setWindowS] = useSticky<number>('zoomWindowS', 30, opts.seedWindowS);
  const [futureS, setFutureS] = useSticky<number>('futureBufferS', 10, opts.seedFutureS);
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

  /** Enabling follow snaps to the playhead keeping the CURRENT window size
   * (the size you were looking at carries over; position jumps to now). */
  const setFollowSnapped = useCallback((on: boolean) => {
    if (on) {
      const s = stable.current;
      const cur = !s.follow && s.manualWin
        ? s.manualWin
        : { startMs: 0, endMs: s.windowS * 1000 };
      const spanS = Math.max(2, Math.round((cur.endMs - cur.startMs) / 1000));
      setWindowS(spanS);
      setFutureS((f) => Math.min(f, Math.round(spanS / 3)));
    }
    setFollow(on);
  }, [setFollow, setWindowS, setFutureS]);

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
