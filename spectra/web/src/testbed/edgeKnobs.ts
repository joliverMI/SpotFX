/** The `edges` engine's three knobs (spectra/services/rhythmic_edges.py) —
 * kept as a pure module (report/AGENTS.md convention: the frontend recomputes
 * locally on every drag, so a `.mjs` proof can transpile and drive this
 * directly, same as testbed/metrics.ts and testbed/songSearch.ts). */

export const DEFAULT_WINDOW_BEATS = 8;
export const DEFAULT_SENSITIVITY = 0.5;
export const DEFAULT_DIRECTION: Direction = 'both';
export const MIN_WINDOW_BEATS = 1;
export const MAX_WINDOW_BEATS = 16;
export const MIN_SENSITIVITY = 0.2;
export const MAX_SENSITIVITY = 1.5;

export type Direction = 'both' | 'up' | 'down';
export const DIRECTIONS: Direction[] = ['both', 'up', 'down'];

export function clampWindowBeats(v: number): number {
  if (!Number.isFinite(v)) return DEFAULT_WINDOW_BEATS;
  return Math.max(MIN_WINDOW_BEATS, Math.min(MAX_WINDOW_BEATS, Math.round(v)));
}

export function clampSensitivity(v: number): number {
  if (!Number.isFinite(v)) return DEFAULT_SENSITIVITY;
  return Math.max(MIN_SENSITIVITY, Math.min(MAX_SENSITIVITY, v));
}

/** Report section 3's "third, coarser knob" (up / down / both) — an
 * out-of-range value (never reachable from the toggle itself, but a
 * defensive default for any other caller) falls back to `both`, matching
 * the backend's own `clamp_direction`. */
export function clampDirection(v: string): Direction {
  return (DIRECTIONS as string[]).includes(v) ? (v as Direction) : DEFAULT_DIRECTION;
}

/** Whether the window/sensitivity/direction knobs have any live effect on
 * the currently active A/B lanes — shown while an `edges` lane, or the
 * `generator` engine's own `preview` kind (2026-09-23: the R3 placement
 * rule reads these same three knobs — spectra/services/midsong_generator.py
 * candidate_moments), is selected in either slot. The `generator` engine's
 * OTHER kind, `stored`, ignores them entirely (it is exactly what is
 * currently written, not recomputed), so a bare engine-name check is not
 * enough here — showing the knobs for a lane they don't touch would imply
 * a control that does nothing. */
export function knobsRelevant(lanes: ({ engine: string; kind?: string } | null | undefined)[]): boolean {
  return lanes.some((l) => l && (l.engine === 'edges'
    || (l.engine === 'generator' && l.kind === 'preview')));
}
