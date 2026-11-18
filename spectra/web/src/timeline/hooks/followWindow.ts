/** The follow window's arithmetic, kept pure (no React) so an executable
 * spec can drive it: scripts/check_timeline_follow_playhead.mjs.
 *
 * THE ONE RULE: in follow mode the window is anchored on the SAME number
 * the playhead layer draws — `drawnPlayheadMs(canvasNowMs, offsetMs)`, the
 * audible clock shifted by the song's shape offset — never on the raw
 * progress clock. The two used to differ by the whole shape offset (the
 * Admiral, 2026-10-07, on Pop Off: "the playhead appears to be ahead of the
 * scrolling view"): that song's stored offset is 14,450 ms, more than the
 * 10 s future buffer, so the playhead was drawn past the window's right
 * edge for the entire song while the window scrolled on. 26 of his songs
 * carry an offset over 10 s and 226 over 2 s, so this was never one song's
 * quirk. The Now Playing page always anchored on the drawn playhead; the
 * Timeline pages now do the same. */

export interface Win {
  startMs: number;
  endMs: number;
}

/** Where the playhead layer draws: the canvas clock plus the shape offset
 * (canvas/layers.ts's playhead layer reads this, so the anchor and the line
 * cannot disagree). */
export function drawnPlayheadMs(canvasNowMs: number, offsetMs: number): number {
  return canvasNowMs + offsetMs;
}

/** Follow mode: [anchor + future − window, anchor + future], clamped into
 * the song. `anchorMs` must be the drawn playhead position. */
export function followWindowFor(
  anchorMs: number, windowS: number, futureS: number, durationMs: number,
): Win {
  const winMs = windowS * 1000;
  const end = anchorMs + futureS * 1000;
  return clampWin({ startMs: end - winMs, endMs: end }, Math.max(1, durationMs), winMs);
}

/** CENTERED follow (the Admiral, 2026-11-18: "the playhead is always
 * centered"): [anchor − window/2, anchor + window/2] — the playhead sits
 * dead centre and the graph scrolls under it, same as the song strip's own
 * rAF-moved playhead. Deliberately NOT run through `clampWin`: clamping to
 * [0, duration] would shove the window off-centre for the first/last half
 * window of a song, which is exactly the edge case this is for. The
 * uncovered span beyond 0 or the song's end draws as nothing — every layer
 * that reads `win.startMs`/`win.endMs` already skips a timestamp outside
 * its own data (`windowIndices` in canvas/layers.ts) — so it comes out as
 * blank padding, not a clamp-driven jump. */
export function centeredWindowFor(anchorMs: number, windowS: number): Win {
  const half = Math.max(500, windowS * 1000) / 2;
  return { startMs: anchorMs - half, endMs: anchorMs + half };
}

export function clampWin(win: Win, durationMs: number, minSpanMs = 1000): Win {
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
