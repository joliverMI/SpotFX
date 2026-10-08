/** Single-finger touch panning on the audio-shape canvas (the Admiral,
 * 2026-10-08: "i want to be able to drag the audio shape graph somehow on
 * a tablet or phone... single finger if it would work well"). A touch
 * that lands on nothing draggable (no marker/flare/trigger under it) is a
 * PAN CANDIDATE until the finger has moved far enough to say which way —
 * horizontal pans the window (the same math the existing middle-mouse pan
 * already uses), vertical is left to the browser's own page scroll. A
 * touch that lands ON a marker is never a pan candidate at all: the hit
 * test already runs first, so dragging a marker and panning the empty
 * graph can never fight each other — see TimelineCanvas.tsx's `down()`.
 *
 * Pure, DOM-free, so scripts/check_timeline_touch_pan.mjs can drive it
 * with no browser — the followWindow.ts precedent. */

/** How far (px) the finger must move, on whichever axis moves further,
 * before the gesture resolves to a pan or a scroll. Small enough that a
 * real pan starts promptly; see TimelineCanvas.tsx for why this also has
 * to beat the browser's own touch-action commit, approximately. */
export const TOUCH_PAN_LOCK_PX = 6;

export type TouchPanLock = 'pan' | 'vertical' | null;

/** Decide a still-undecided single-finger touch's direction from its
 * accumulated displacement since touch-down. `null` means "not enough
 * movement yet to tell" — call again on the next move. Ties (equal |dx|
 * and |dy|) resolve to 'pan': a horizontal drag is the more deliberate,
 * less accidental gesture on a WIDE graph, so a genuine ambiguity should
 * not silently hand the gesture to page scroll. */
export function resolveTouchPanLock(dx: number, dy: number): TouchPanLock {
  const adx = Math.abs(dx);
  const ady = Math.abs(dy);
  if (Math.max(adx, ady) < TOUCH_PAN_LOCK_PX) return null;
  return adx >= ady ? 'pan' : 'vertical';
}

/** The pan's own delta, in song-ms — the identical formula the existing
 * middle-mouse-drag pan already uses (TimelineCanvas.tsx's `move()`):
 * drag right -> window moves right. Factored out so both the mouse path
 * and the touch path can never silently diverge on this arithmetic. */
export function panDeltaMs(
  xNow: number,
  xStart: number,
  canvasW: number,
  winStartMs: number,
  winEndMs: number,
): number {
  const span = winEndMs - winStartMs;
  return ((xNow - xStart) / Math.max(1, canvasW)) * span;
}
