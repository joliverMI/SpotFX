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

/** The "strongest N" density knob (data/transition-alignment-plan/
 * report.md section 5 task 4) — same bounds/default as
 * RoomControlState.transition_max_per_song's own Field(ge=6, le=40,
 * default=12) in spectra/services/room_controls.py; kept as a hand-typed
 * copy here rather than fetched, the same way DEFAULT_WINDOW_BEATS/
 * DEFAULT_SENSITIVITY above already mirror rhythmic_edges.py's own
 * constants — the backend's own field validation is the enforced source
 * of truth, this is only what the slider's own bounds show. */
export const DEFAULT_MAX_PER_SONG = 12;
export const MIN_MAX_PER_SONG = 6;
export const MAX_MAX_PER_SONG = 40;

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

export function clampMaxPerSong(v: number): number {
  if (!Number.isFinite(v)) return DEFAULT_MAX_PER_SONG;
  return Math.max(MIN_MAX_PER_SONG, Math.min(MAX_MAX_PER_SONG, Math.round(v)));
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

/** The density ("strongest N") knob is narrower than the three above — it
 * only has meaning for the generator's own preview kind (rhythmic edges
 * are just detected, never ranked or trimmed, so showing this slider next
 * to an `edges` lane would be a control that does nothing there). */
export function maxPerSongRelevant(lanes: ({ engine: string; kind?: string } | null | undefined)[]): boolean {
  return lanes.some((l) => l && l.engine === 'generator' && l.kind === 'preview');
}

/** "Use as room default" (report section 5 task 4) — the ONE write these
 * three sliders can make, through the existing `PUT /api/room-controls`
 * partial merge. Kept pure so the confirm text and the exact payload can
 * be proven without rendering React (this repo carries no DOM/component
 * test harness — see edgeKnobs.ts's own header comment and AGENTS.md's
 * "Tests" section). */
export interface TransitionKnobValues {
  windowBeats: number;
  sensitivity: number;
  maxPerSong: number;
}

/** `null`/`undefined` room defaults (still loading, or never fetched) read
 * as "no difference" — there is nothing yet to diverge from. */
export function transitionDefaultsDiffer(
  current: TransitionKnobValues,
  room: TransitionKnobValues | null | undefined,
): boolean {
  if (!room) return false;
  return current.windowBeats !== room.windowBeats
    || Math.abs(current.sensitivity - room.sensitivity) > 1e-9
    || current.maxPerSong !== room.maxPerSong;
}

export function useAsRoomDefaultConfirmMessage(current: TransitionKnobValues): string {
  return `Set the room's own transition placement defaults to Window `
    + `${current.windowBeats} beat${current.windowBeats === 1 ? '' : 's'}, `
    + `Sensitivity ${current.sensitivity.toFixed(2)}, and up to `
    + `${current.maxPerSong} transitions per song? This changes what `
    + '"⟳ Generate" produces for every song from now on.';
}

/** The exact PUT /api/room-controls partial-merge fields this button
 * writes — direction is deliberately excluded, it has no room-level
 * setting (see RoomControlState.transition_window_beats's own docstring
 * in spectra/services/room_controls.py). */
export function roomControlsPatchForUseAsDefault(current: TransitionKnobValues) {
  return {
    transition_window_beats: current.windowBeats,
    transition_edge_sensitivity: current.sensitivity,
    transition_max_per_song: current.maxPerSong,
  };
}
