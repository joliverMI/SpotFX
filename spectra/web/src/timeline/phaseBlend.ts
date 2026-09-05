/** CHARGE/LULL PHASE BLEND — the drawable half of SPECTRA's own "override
 * blend", mirrored from the engine so the graph shows what the room does.
 *
 * THE FACT THIS MODULE EXISTS FOR: in SPECTRA a charge or lull ramp
 * stretches to the real gap to the next trigger UNCONDITIONALLY, for every
 * one of them — spectra/services/scene_response.py::_phase_ramp_ms, whose
 * gap comes from trigger_engine._next_trigger_gap_ms. There is no per-
 * trigger flag gating it; the per-scene PhaseBlend knob that once carried
 * the static half was RETIRED 2026-08-20 (Admiral order "fix the lull
 * ramp"). So a charge/lull blend is keyed on the CLASS, never on a stored
 * `override_blend` flag his charge/lull triggers may or may not carry — 64
 * of his 338 real charge/lull triggers carry it False while the engine
 * blends them anyway, which is exactly the omission this draws away.
 *
 * The numbers below are the engine's own, mirrored (nothing serves them
 * over the wire). If _phase_ramp_ms changes, change them here too — a ruler
 * that quietly disagrees with the show is worse than no ruler.
 */

/** The flat, hand-tuned fallback the engine uses when the gap is
 * UNKNOWABLE — for the graph, that means a charge/lull with no later
 * enabled trigger to stretch toward. scene_response.PHASE_RAMP_MS. */
export const PHASE_RAMP_MS: Record<string, number> = { charge: 4000, lull: 2500, drop: 400 };

/** scene_response.PHASE_RAMP_HANG_FRACTION — the ramp reaches full at ~90%
 * of the gap and HANGS at 1.0 for the last ~10% (his spec: the blob should
 * "reach the center just and hang for just a moment ... before the
 * explosion"). Drawn as a distinct, lighter band so the hang reads as the
 * pause it is rather than as more ramp. */
export const PHASE_RAMP_HANG_FRACTION = 0.10;

/** scene_response.PHASE_RAMP_MIN_MS — floor on the stretched ramp itself. */
export const PHASE_RAMP_MIN_MS = 200;

/** scene_response.PHASE_RAMP_STRETCH_CLASSES — drop is NEVER stretched. */
export function isPhaseStretchClass(eventClass: string | null | undefined): boolean {
  return eventClass === 'charge' || eventClass === 'lull';
}

/** The engine's own ramp length for one fire. gapMs === null means there is
 * nothing to stretch toward — the documented flat-default degradation, never
 * a guess. Mirrors scene_response._phase_ramp_ms exactly. */
export function phaseRampMs(eventClass: string, gapMs: number | null): number {
  if (isPhaseStretchClass(eventClass) && gapMs !== null && gapMs > 0) {
    return Math.max(PHASE_RAMP_MIN_MS, Math.round(gapMs * (1 - PHASE_RAMP_HANG_FRACTION)));
  }
  return PHASE_RAMP_MS[eventClass] ?? 0;
}

/** One charge/lull blend as it should be drawn: the ramp runs
 * [startMs, rampEndMs) and then HANGS at full until endMs. When the gap is
 * unknowable the whole span IS the flat default ramp and there is no hang
 * (rampEndMs === endMs) — which is what the engine actually does, not a
 * span running to the end of the song. */
export interface PhaseBlendSpan {
  startMs: number;
  rampEndMs: number;
  endMs: number;
  /** true when the length came from a real next trigger; false when it is
   * the flat class default because there was nothing to stretch toward. */
  stretched: boolean;
}

/** Resolve one charge/lull trigger's drawn blend. nextMs is the timestamp of
 * the next trigger that will actually fire (null = none) — the same quantity
 * trigger_engine._next_trigger_gap_ms resolves at fire time. */
export function phaseBlendSpan(
  eventClass: string,
  startMs: number,
  nextMs: number | null,
): PhaseBlendSpan {
  const gap = nextMs !== null && nextMs > startMs ? nextMs - startMs : null;
  const ramp = phaseRampMs(eventClass, gap);
  const end = gap !== null ? startMs + gap : startMs + ramp;
  return { startMs, rampEndMs: Math.min(startMs + ramp, end), endMs: end, stretched: gap !== null };
}
