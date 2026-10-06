/** The Drops lane's controls (spectra/services/drop_detector.py, the
 * drop-detection plan's phase 2: "a Drops lane on the test bed scores it
 * against your marks on any song, so the two thresholds can be tuned by
 * eye before anything fires") — the two tier thresholds, PLUS the drop
 * floor (2026-10-06, the Admiral's own setting: a drop is only generated
 * where the music during or right after it reaches at least this section
 * energy). A pure module, the edgeKnobs.ts precedent, so
 * scripts/check_testbed_drop_knobs.mjs can transpile and drive it with
 * no DOM.
 *
 * Bounds and defaults mirror RoomControlState.drop_confident_score /
 * drop_suggested_score (spectra/services/room_controls.py: Field(ge=0.3,
 * le=2.0), defaults 1.0 / 0.7 — the plan's measured operating points) and
 * drop_floor (Field(ge=0.0, le=1.0), default 0.95 — a DIFFERENT scale,
 * section energy_rms rather than a detector score). The backend's own
 * field validation is the enforced source of truth; this is only what
 * the sliders show. */

export const DEFAULT_CONFIDENT_SCORE = 1.0;
export const DEFAULT_SUGGESTED_SCORE = 0.7;
export const MIN_DROP_SCORE = 0.3;
export const MAX_DROP_SCORE = 2.0;

export const DEFAULT_DROP_FLOOR = 0.95;
export const MIN_DROP_FLOOR = 0.0;
export const MAX_DROP_FLOOR = 1.0;

/** The kinds the `drops` engine emits (testbed_engines.ENGINES['drops']). */
export const DROP_KINDS = ['drop', 'drop_confident', 'lull', 'charge'];

export function clampDropScore(v: number, fallback: number): number {
  if (!Number.isFinite(v)) return fallback;
  return Math.max(MIN_DROP_SCORE, Math.min(MAX_DROP_SCORE, Math.round(v * 100) / 100));
}

export function clampDropFloor(v: number, fallback: number): number {
  if (!Number.isFinite(v)) return fallback;
  return Math.max(MIN_DROP_FLOOR, Math.min(MAX_DROP_FLOOR, Math.round(v * 100) / 100));
}

/** The sliders only mean anything while a `drops` lane is selected in
 * either A/B slot — a knob shown for an engine it does not touch implies a
 * control that does nothing. */
export function dropKnobsRelevant(lanes: ({ engine: string; kind?: string } | null | undefined)[]): boolean {
  return lanes.some((l) => !!l && l.engine === 'drops');
}

/** A drops lane is scored at ONE BEAT — the plan's own measure ("a drop
 * counts as found within one beat of his mark"). */
export function isDropKind(kind: string): boolean {
  return DROP_KINDS.includes(kind);
}

export interface DropKnobValues {
  confident: number;
  suggested: number;
  floor: number;
}

function changed(current: DropKnobValues, room: DropKnobValues) {
  return {
    confident: Math.abs(current.confident - room.confident) > 1e-9,
    suggested: Math.abs(current.suggested - room.suggested) > 1e-9,
    floor: Math.abs(current.floor - room.floor) > 1e-9,
  };
}

/** null/undefined room values (still loading) read as "no difference". */
export function dropDefaultsDiffer(current: DropKnobValues, room: DropKnobValues | null | undefined): boolean {
  if (!room) return false;
  const c = changed(current, room);
  return c.confident || c.suggested || c.floor;
}

/** Names ONLY the threshold(s) that actually move. */
export function dropUseAsRoomDefaultConfirmMessage(current: DropKnobValues, room: DropKnobValues): string {
  const c = changed(current, room);
  const parts: string[] = [];
  if (c.confident) parts.push(`confident from ${current.confident.toFixed(2)}`);
  if (c.suggested) parts.push(`suggested from ${current.suggested.toFixed(2)}`);
  if (c.floor) parts.push(`energy floor from ${current.floor.toFixed(2)}`);
  if (parts.length === 0) {
    return 'The sliders already match the room\'s current drop settings — nothing to change.';
  }
  return `Set the room's drop setting${parts.length === 1 ? '' : 's'} — ${parts.join('; ')}? `
    + 'Each song is detected again under the new values the next time it plays. '
    + 'Nothing fires from drop detection yet.';
}

/** The exact PUT /api/room-controls partial-merge fields — only the
 * setting(s) that differ from the room's own. */
export function dropRoomControlsPatch(current: DropKnobValues, room: DropKnobValues): Partial<{
  drop_confident_score: number;
  drop_suggested_score: number;
  drop_floor: number;
}> {
  const c = changed(current, room);
  const patch: Partial<{
    drop_confident_score: number; drop_suggested_score: number; drop_floor: number;
  }> = {};
  if (c.confident) patch.drop_confident_score = current.confident;
  if (c.suggested) patch.drop_suggested_score = current.suggested;
  if (c.floor) patch.drop_floor = current.floor;
  return patch;
}

/** One beat in ms at this tempo, clamped to the tolerance slider's own
 * range — the Drops lanes' default tolerance. */
export function oneBeatToleranceMs(tempoBpm: number | null, minMs: number, maxMs: number): number {
  if (!tempoBpm || tempoBpm <= 0) return 500;
  return Math.min(maxMs, Math.max(minMs, Math.round(60000 / tempoBpm)));
}
