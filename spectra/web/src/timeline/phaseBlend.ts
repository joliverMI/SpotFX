/** CHARGE/LULL PHASE BLEND — the drawable half of SPECTRA's own "override
 * blend", mirrored from the engine so the graph shows what the room does.
 *
 * THE FACT THIS MODULE EXISTS FOR: in SPECTRA a charge or lull ramp
 * stretches to the real gap to where its build ends UNCONDITIONALLY, for
 * every one of them — spectra/services/scene_response.py::_phase_ramp_ms,
 * whose gap comes from trigger_engine._phase_partner_gap_ms. There is no per-
 * trigger flag gating it; the per-scene PhaseBlend knob that once carried
 * the static half was RETIRED 2026-08-20 (Admiral order "fix the lull
 * ramp"). So a charge/lull blend is keyed on the CLASS, never on a stored
 * `override_blend` flag his charge/lull triggers may or may not carry — 64
 * of his 338 real charge/lull triggers carry it False while the engine
 * blends them anyway, which is exactly the omission this draws away.
 *
 * WHERE A BUILD ENDS — the PHASE PARTNER rule (2026-10-06, drop-detection
 * plan phase 1; spectra/services/phase_partner.py is the binding
 * statement, phaseBuildTarget below its mirror): a charge builds to its own
 * next lull or drop and a lull to its own next drop, whatever flare, scene
 * change or colour change sits between, if that partner is within the
 * effects' own 60 s cap. A charge or lull with no partner ahead keeps the
 * pre-rule answer: the next trigger of any kind.
 *
 * The numbers below are the engine's own, mirrored (nothing serves them
 * over the wire). If _phase_ramp_ms or phase_partner.py changes, change
 * them here too — a ruler that quietly disagrees with the show is worse
 * than no ruler. scripts/check_charge_lull_blend_spans.mjs reads both
 * Python modules and goes red when they drift.
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
  /** true when the length came from a real later trigger; false when it is
   * the flat class default because there was nothing to stretch toward. */
  stretched: boolean;
}

/** Resolve one charge/lull trigger's drawn blend. nextMs is the timestamp the
 * build ends on (null = none) — the same quantity
 * trigger_engine._phase_partner_gap_ms resolves at fire time; use
 * phaseBlendSpanFor to resolve it from the song's triggers. */
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

/** phase_partner.PHASE_ORDER — a later class is a partner, the same or an
 * earlier one is a restart (it rewrites phase_progress to 0 itself). */
export const PHASE_ORDER: Record<string, number> = { charge: 0, lull: 1, drop: 2 };

/** True for 'charge' / 'lull' / 'drop' — an own-property check, so a
 * stray class name that happens to be an Object prototype key never
 * reads as a phase. */
export function isPhaseClass(cls: string | null | undefined): cls is string {
  return typeof cls === 'string' && Object.prototype.hasOwnProperty.call(PHASE_ORDER, cls);
}

/** phase_partner.PARTNER_REACH_MS — the effects' own absolute charge/lull
 * cap (fx/effects/particle_handoff.PHASE_HOLD_MAX_S, 60 s). */
export const PHASE_PARTNER_REACH_MS = 60_000;

/** phase_partner.TARGET_* — what a build ends on. */
export type PhaseBuildReason = 'partner' | 'next_trigger' | 'none';

export interface PhaseBuildTarget {
  /** null exactly when reason === 'none'. */
  ms: number | null;
  reason: PhaseBuildReason;
  /** the target's phase class, or null when it is not a phase trigger. */
  targetClass: string | null;
}

/** One later trigger, as the partner rule sees it: its time and its phase
 * class ('charge' / 'lull' / 'drop'), or null for anything that writes no
 * phase (a flare, a scene change, a colour change, an update). */
export interface LaterMoment {
  ms: number;
  phaseClass: string | null;
}

/** True when laterClass completes eventClass's build: a lull or drop for a
 * charge, a drop for a lull. Mirrors phase_partner.is_partner. */
export function isPhasePartner(eventClass: string, laterClass: string | null): boolean {
  if (!isPhaseStretchClass(eventClass) || !isPhaseClass(laterClass)) return false;
  return PHASE_ORDER[laterClass] > PHASE_ORDER[eventClass];
}

/** Where one charge/lull's build ends. Mirrors phase_partner.build_target
 * exactly: the next PHASE trigger, if it is a partner within the reach;
 * otherwise the next trigger of any kind (the pre-rule answer); otherwise
 * nothing. `later` is every OTHER trigger that will fire — order does not
 * matter, and anything at or before startMs is ignored. */
export function phaseBuildTarget(
  eventClass: string,
  startMs: number,
  later: LaterMoment[],
): PhaseBuildTarget {
  if (!isPhaseStretchClass(eventClass)) return { ms: null, reason: 'none', targetClass: null };
  const ahead = later.filter((m) => m.ms > startMs).sort((a, b) => a.ms - b.ms);
  if (ahead.length === 0) return { ms: null, reason: 'none', targetClass: null };
  const nextPhase = ahead.find((m) => isPhaseClass(m.phaseClass));
  if (nextPhase && isPhasePartner(eventClass, nextPhase.phaseClass)
      && nextPhase.ms - startMs <= PHASE_PARTNER_REACH_MS) {
    return { ms: nextPhase.ms, reason: 'partner', targetClass: nextPhase.phaseClass };
  }
  const first = ahead[0];
  return { ms: first.ms, reason: 'next_trigger',
    targetClass: isPhaseClass(first.phaseClass) ? first.phaseClass : null };
}

/** phaseBlendSpan with the build's end resolved by the partner rule, plus
 * what it ends on (for the hover note). */
export function phaseBlendSpanFor(
  eventClass: string,
  startMs: number,
  later: LaterMoment[],
): PhaseBlendSpan & { buildsTo: PhaseBuildTarget } {
  const buildsTo = phaseBuildTarget(eventClass, startMs, later);
  return { ...phaseBlendSpan(eventClass, startMs, buildsTo.ms), buildsTo };
}
