/** THE ONE PHASE-ARM BUTTON — "next drop, lull, and charge" as a single
 * control, his ask verbatim (2026-10-19): "on the light show events, add
 * a button for next drop, lull, and charge. make it one button that
 * cycles through those to reduce clutter. use thr icons and colors from
 * the timeline for those events."
 *
 * ONE BUTTON, FOUR STATES. A tap advances its armed target:
 *
 *     off  →  next drop  →  next lull  →  next charge  →  off
 *
 * — PHASE_CYCLE's own order, which is the order he named them in and the
 * same order as show_arms.PHASE_TRIGGERS. Off looks like any other
 * unarmed icon button; armed wears the Timeline's own glyph and colour
 * for that phase, so the button and the shape it is waiting for read as
 * the same thing.
 *
 * THE ICON AND THE COLOUR ARE IMPORTED, NEVER COPIED. `pulse` is
 * iconRegistry's generic drop-sequence phase glyph (charge, lull and
 * drop all share it on the Timeline's own next-event box) and
 * PHASE_COLOR is ../timeline/dropSequences' one definition of gold /
 * sky / magenta — decision 5 there: those three colours belong to the
 * phases and nothing else on the Timeline may wear them. A hex literal
 * in this file would be a second definition and is exactly what the
 * import exists to prevent.
 *
 * THE STATE IS LIVE `arms`, NEVER A LOCAL CLICK FLAG — the rule the other
 * four icons in the Run view already follow: `phaseArmed` reads whatever
 * the armed board says, so arming or disarming from Sonic, the Build view
 * or another screen moves this button with no tap here.
 *
 * CYCLING IS DISARM-THEN-ARM. show_arms' replace rule is "the same set on
 * the SAME trigger", so arming drop→lull would otherwise leave the set
 * armed on both: `cycleActions` always names the arms to drop first. It
 * is the caller's one source of what a tap does.
 *
 * Pure and DOM-free, so scripts/check_phase_arm_cycle.mjs drives it
 * directly. */
import type { IconName } from '../components/iconRegistry';
import { PHASE_COLOR } from '../timeline/dropSequences';
import { TRIGGER_LABEL } from './showSummary';
import type { ArmPhase, ShowArm, SongPhases } from './types';

/** His own order: drop, then lull, then charge. */
export const PHASE_CYCLE: ArmPhase[] = ['drop', 'lull', 'charge'];

/** The generic drop-sequence phase glyph — the colour distinguishes them
 * (iconRegistry.ts's own `pulse` docstring). */
export const PHASE_ICON: IconName = 'pulse';

/** Which phase a set is currently armed on, or null when none. Earliest
 * in PHASE_CYCLE wins if several are somehow armed at once (possible from
 * Sonic or the Build view, which arm one trigger at a time) — so the next
 * tap advances from a defined place rather than an arbitrary one. */
export function phaseArmed(armedOn: Iterable<string>): ArmPhase | null {
  const set = new Set(armedOn);
  return PHASE_CYCLE.find((p) => set.has(p)) ?? null;
}

/** The phase a tap moves to: the next in PHASE_CYCLE, or null (off) after
 * the last one — and `drop` from off. */
export function nextPhase(current: ArmPhase | null): ArmPhase | null {
  if (current === null) return PHASE_CYCLE[0];
  const i = PHASE_CYCLE.indexOf(current);
  if (i < 0) return PHASE_CYCLE[0];
  return i + 1 < PHASE_CYCLE.length ? PHASE_CYCLE[i + 1] : null;
}

export interface PhaseCycleActions {
  /** every phase arm on this set to cancel first (ids), so the set is
   * never left armed on two phases at once */
  disarmIds: string[];
  /** the phase to arm after that, or null when the tap turns it off */
  arm: ArmPhase | null;
}

/** What one tap does, given this set's own arms. `setArms` is the arms
 * already filtered to the set the button belongs to. */
export function cycleActions(setArms: ShowArm[]): PhaseCycleActions {
  const onPhases = setArms.filter((a) => (PHASE_CYCLE as string[]).includes(a.on));
  const arm = nextPhase(phaseArmed(onPhases.map((a) => a.on)));
  // EVERY phase arm, not just the one the cycle is advancing from: that is
  // what makes a tap self-correcting if an earlier cancel ever failed.
  return { disarmIds: onPhases.map((a) => a.id), arm };
}

export interface PhaseButtonLook {
  /** the phase it is armed on, null when off */
  phase: ArmPhase | null;
  icon: IconName;
  /** the Timeline's own colour for that phase, or undefined when off (so
   * the button keeps the shared unarmed look) */
  color: string | undefined;
  /** the phase a tap moves to, for the label */
  next: ArmPhase | null;
  /** hover text: what it is waiting for, or what a tap will do */
  title: string;
  /** the accessible label, naming the set and the phase (never a colour —
   * colour alone never carries meaning for assistive tech) */
  ariaLabel: string;
}

/** Everything the button renders from, in one object. `setName` is the
 * set's own name, for the accessible label. `phases` (optional) adds
 * what this song actually holds, so a song with no drop sequences SAYS
 * so instead of the button silently waiting forever — the same honesty
 * the High/Low flags carry for a song with no High. */
export function phaseButtonLook(
  setArms: ShowArm[], setName: string, phases?: SongPhases | null,
): PhaseButtonLook {
  const phase = phaseArmed(setArms.map((a) => a.on));
  const next = nextPhase(phase);
  const color = phase ? PHASE_COLOR[phase] : undefined;
  const nextWords = next ? `arm: ${TRIGGER_LABEL[next]}` : 'turn it off';
  const title = phase
    ? `Armed: ${TRIGGER_LABEL[phase]}${phaseNote(phase, phases)} — tap to ${nextWords}`
    : `Arm: ${TRIGGER_LABEL[PHASE_CYCLE[0]]} (tap again for ${PHASE_CYCLE.slice(1).join(', then ')})`;
  const ariaLabel = phase
    ? `${setName} is armed for the ${TRIGGER_LABEL[phase]}; activate to ${nextWords}`
    : `Arm ${setName} for the ${TRIGGER_LABEL[PHASE_CYCLE[0]]}`;
  return { phase, icon: PHASE_ICON, color, next, title, ariaLabel };
}

/** " — no drop on this song, so it waits" / " — 13 drops on this song",
 * or "" when the song's phases are not known yet (never a guess). */
export function phaseNote(phase: ArmPhase, phases?: SongPhases | null): string {
  if (!phases || !phases.known) return '';
  const n = phases.counts?.[phase] ?? 0;
  if (n === 0) return ` — no ${phase} on this song, so it waits`;
  return ` — ${n} ${phase}${n === 1 ? '' : 's'} on this song`;
}
