/** THE DROP MARK'S DRAG — the arithmetic behind dragging the drop's red
 * line on a scene's drop-sequence preview (2026-10-12, the Admiral: "I
 * wanted to be able to edit red line for the drop in the preview drop
 * sequence page for a scene, but I cannot click it and drag it ... the view
 * is pretty crowded and it's hard to click on anything, and also, it should
 * work on a touch screen (tablet)").
 *
 * WHAT A DRAG WRITES: the scene's own SceneV2.drop_timing_offset_ms
 * (spectra/services/drop_timing.py — OFFSET family, ms, NEGATIVE = the drop
 * fires EARLIER). The ruler is song time, so the line moves the way the
 * drop moves: drag LEFT = earlier = more negative. The offset is measured
 * from the music's own drop mark, which the server returns as the drop
 * mark's `music_mark_s` — this module never invents a moment of its own,
 * it only inverts that one mapping.
 *
 * WHAT IS DRAWN WHERE THE SERVER WILL DRAW IT: a drop never moves to within
 * MIN_BUILD_MS of its own lull (drop_timing.shift_drop_ms), so on a short
 * lull gap an offset can be stored that this ruler cannot fully apply.
 * `floor_applied_ms` (server-computed) is the earliest the drop can land
 * here; `appliedOffsetMs` holds the line there exactly as the server will,
 * while the stored offset stays what he set (a real song's lull is seconds
 * ahead, so the full offset applies there).
 *
 * Pure, DOM-free — scripts/check_drop_marker_drag.mjs drives it directly. */

/** The server's `drop_timing` block on a sequence preview timeline
 * (spectra/services/phase_preview.build_timeline). */
export interface DropTimingInfo {
  offset_ms: number;
  applied_ms: number;
  source: 'scene' | 'room' | 'default';
  scene_offset_ms?: number | null;
  room_offset_ms?: number | null;
  min_ms?: number;
  max_ms?: number;
  floor_applied_ms?: number;
}

/** A drag lands on this grid (ms). */
export const DROP_SNAP_MS = 10;
/** A drag within this many ms of "on the mark" (0) or the room's value is
 * pulled onto it — the two values worth landing on exactly. */
export const DROP_MAGNET_MS = 30;
/** The nudge buttons (and ←/→, Shift = the big step). */
export const NUDGE_SMALL_MS = 10;
export const NUDGE_BIG_MS = 50;
export const NUDGE_STEPS: readonly number[] = [-NUDGE_BIG_MS, -NUDGE_SMALL_MS,
  NUDGE_SMALL_MS, NUDGE_BIG_MS];

const DEFAULT_MIN_MS = -2000;
const DEFAULT_MAX_MS = 2000;

export function clampOffsetMs(ms: number, info?: DropTimingInfo | null): number {
  const lo = info?.min_ms ?? DEFAULT_MIN_MS;
  const hi = info?.max_ms ?? DEFAULT_MAX_MS;
  return Math.max(lo, Math.min(hi, Math.round(ms)));
}

/** The offset that puts the drop at ruler time `s`. */
export function offsetAtS(s: number, musicMarkS: number): number {
  return Math.round((s - musicMarkS) * 1000);
}

/** The values a drag snaps onto exactly: on the mark, and the room's. */
export function magnetsFor(info?: DropTimingInfo | null): number[] {
  const out = [0];
  const room = info?.room_offset_ms;
  if (room != null && room !== 0) out.push(room);
  return out;
}

/** Snap a raw offset: onto a magnet within DROP_MAGNET_MS (named in
 * `snappedTo`), else onto the DROP_SNAP_MS grid. */
export function snapOffsetMs(ms: number, magnets: number[] = [0],
                             stepMs = DROP_SNAP_MS, magnetMs = DROP_MAGNET_MS
): { ms: number; snappedTo: number | null } {
  let best: number | null = null;
  for (const m of magnets) {
    if (Math.abs(ms - m) <= magnetMs && (best === null || Math.abs(ms - m) < Math.abs(ms - best))) {
      best = m;
    }
  }
  if (best !== null) return { ms: best, snappedTo: best };
  return { ms: Math.round(ms / stepMs) * stepMs, snappedTo: null };
}

/** The offset this ruler actually applies for a stored `ms` — the server's
 * clamp (drop_timing.shift_drop_ms): a NEGATIVE offset stops at the lull's
 * floor; a later-than-mark one is never clamped. */
export function appliedOffsetMs(ms: number, info?: DropTimingInfo | null): number {
  const floor = info?.floor_applied_ms;
  if (ms < 0 && floor != null) return Math.max(ms, floor);
  return ms;
}

/** Where the drop's line sits on the ruler for a stored offset. */
export function markSForOffset(ms: number, musicMarkS: number,
                               info?: DropTimingInfo | null): number {
  return musicMarkS + appliedOffsetMs(ms, info) / 1000;
}

/** One drag step: the pointer's ruler time (grab offset already applied)
 * to the offset it sets — snapped, then clamped to the legal range. */
export function dragToOffset(s: number, musicMarkS: number,
                             info?: DropTimingInfo | null
): { ms: number; snappedTo: number | null } {
  const raw = clampOffsetMs(offsetAtS(s, musicMarkS), info);
  const snapped = snapOffsetMs(raw, magnetsFor(info));
  return { ms: clampOffsetMs(snapped.ms, info), snappedTo: snapped.snappedTo };
}

/** A nudge button / arrow key from the offset in force. */
export function nudgeOffsetMs(currentMs: number, deltaMs: number,
                              info?: DropTimingInfo | null): number {
  return clampOffsetMs(currentMs + deltaMs, info);
}

/** The offset in force for a scene draft value (null = the room's). */
export function effectiveOffsetMs(sceneMs: number | null | undefined,
                                  info?: DropTimingInfo | null): number {
  if (sceneMs != null) return sceneMs;
  return info?.room_offset_ms ?? info?.offset_ms ?? 0;
}

/** "−400 ms" — a true minus sign, the handle's own readout. */
export function signedMs(ms: number): string {
  if (ms === 0) return '0 ms';
  return `${ms < 0 ? '−' : '+'}${Math.abs(ms)} ms`;
}

/** "400 ms early" / "120 ms late" / "on the mark". */
export function offsetWords(ms: number): string {
  if (ms === 0) return 'on the mark';
  return `${Math.abs(ms)} ms ${ms < 0 ? 'early' : 'late'}`;
}
