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

/** The density RATE knob (2026-09-25, the Admiral's order: "instead of a
 * fixed transition count per song, do per minute" — REPLACES the old flat
 * "strongest N" per-song count, data/transition-alignment-plan/report.md
 * section 5 task 4) — same bounds/default as RoomControlState.
 * transitions_per_minute's own Field(ge=1, le=30, default=8) in
 * spectra/services/room_controls.py; kept as a hand-typed copy here rather
 * than fetched, the same way DEFAULT_WINDOW_BEATS/DEFAULT_SENSITIVITY above
 * already mirror rhythmic_edges.py's own constants — the backend's own
 * field validation is the enforced source of truth, this is only what the
 * slider's own bounds show. The RESOLVED per-song total (rate x duration x
 * that song's own intensity-scale factor) is computed server-side
 * (spectra/services/midsong_generator.py's resolve_transition_count) and
 * is not reproduced here — the slider only ever shows/sets the rate. */
export const DEFAULT_TRANSITIONS_PER_MINUTE = 8;
export const MIN_TRANSITIONS_PER_MINUTE = 1;
export const MAX_TRANSITIONS_PER_MINUTE = 30;

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

export function clampTransitionsPerMinute(v: number): number {
  if (!Number.isFinite(v)) return DEFAULT_TRANSITIONS_PER_MINUTE;
  return Math.max(MIN_TRANSITIONS_PER_MINUTE, Math.min(MAX_TRANSITIONS_PER_MINUTE, v));
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

/** The density (transitions-per-minute) knob is narrower than the three
 * above — it only has meaning for the generator's own preview kind
 * (rhythmic edges are just detected, never ranked or trimmed, so showing
 * this slider next to an `edges` lane would be a control that does
 * nothing there). */
export function transitionsPerMinuteRelevant(lanes: ({ engine: string; kind?: string } | null | undefined)[]): boolean {
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
  transitionsPerMinute: number;
}

/** Which of the three fields actually diverge — the ONE definition both
 * `transitionDefaultsDiffer` (the "differs from room default" highlight)
 * and the confirm-message/patch builders below key off, so they can never
 * disagree about which knob changed. */
function changedTransitionFields(
  current: TransitionKnobValues,
  room: TransitionKnobValues,
): { windowBeats: boolean; sensitivity: boolean; transitionsPerMinute: boolean } {
  return {
    windowBeats: current.windowBeats !== room.windowBeats,
    sensitivity: Math.abs(current.sensitivity - room.sensitivity) > 1e-9,
    transitionsPerMinute: Math.abs(current.transitionsPerMinute - room.transitionsPerMinute) > 1e-9,
  };
}

/** `null`/`undefined` room defaults (still loading, or never fetched) read
 * as "no difference" — there is nothing yet to diverge from. */
export function transitionDefaultsDiffer(
  current: TransitionKnobValues,
  room: TransitionKnobValues | null | undefined,
): boolean {
  if (!room) return false;
  const changed = changedTransitionFields(current, room);
  return changed.windowBeats || changed.sensitivity || changed.transitionsPerMinute;
}

/** Lists only the knob(s) that actually diverge from the room's current
 * values — a user who only ever touched Window must never be told (or
 * have the PUT claim) that Sensitivity or Transitions-per-minute are also
 * changing, since those two still hold whatever the room already had. */
export function useAsRoomDefaultConfirmMessage(
  current: TransitionKnobValues,
  room: TransitionKnobValues,
): string {
  const changed = changedTransitionFields(current, room);
  const parts: string[] = [];
  if (changed.windowBeats) {
    parts.push(`Window to ${current.windowBeats} beat${current.windowBeats === 1 ? '' : 's'}`);
  }
  if (changed.sensitivity) parts.push(`Sensitivity to ${current.sensitivity.toFixed(2)}`);
  if (changed.transitionsPerMinute) {
    parts.push(`${current.transitionsPerMinute} transitions per minute`);
  }
  if (parts.length === 0) {
    return 'The sliders already match the room\'s current defaults — nothing to change.';
  }
  return `Set the room's own transition placement default${parts.length === 1 ? '' : 's'} — `
    + `${parts.join('; ')}? This changes what "⟳ Generate" produces for every song from now on.`;
}

/** The exact PUT /api/room-controls partial-merge fields this button
 * writes — ONLY the knob(s) that actually diverge from the room's current
 * values, never all three unconditionally (a slider the page synced from
 * the room at load and he never touched must not be re-asserted back at
 * whatever it happens to read, which is always the room's own value
 * anyway, but re-sending it invites exactly the "wrote three, meant one"
 * confusion this function exists to avoid). `direction` is deliberately
 * excluded regardless — it has no room-level setting (see
 * RoomControlState.transition_window_beats's own docstring in
 * spectra/services/room_controls.py). */
export function roomControlsPatchForUseAsDefault(
  current: TransitionKnobValues,
  room: TransitionKnobValues,
): Partial<{
  transition_window_beats: number;
  transition_edge_sensitivity: number;
  transitions_per_minute: number;
}> {
  const changed = changedTransitionFields(current, room);
  const patch: Partial<{
    transition_window_beats: number;
    transition_edge_sensitivity: number;
    transitions_per_minute: number;
  }> = {};
  if (changed.windowBeats) patch.transition_window_beats = current.windowBeats;
  if (changed.sensitivity) patch.transition_edge_sensitivity = current.sensitivity;
  if (changed.transitionsPerMinute) patch.transitions_per_minute = current.transitionsPerMinute;
  return patch;
}
