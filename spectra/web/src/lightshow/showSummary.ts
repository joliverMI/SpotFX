/** Pure wording for the Light Show's status surfaces — kept out of React so
 * scripts/check_light_show_summary.mjs can drive it with no DOM. */
import type { ArmTrigger, EndShowReport, ShowArm, ShowBrief, ShowCue, ShowRun } from './types';

/** The top-bar strip's one line, or null when the show holds nothing (the
 * strip is absent then — it costs no space in normal use). */
export function stripLine(b: ShowBrief | null | undefined): string | null {
  if (!b || !b.active) return null;
  const parts: string[] = [];
  if (b.armed) parts.push(`${b.armed} armed`);
  if (b.running_sets) parts.push(`${b.running_sets} running`);
  if (b.holds) parts.push(`${b.holds} holding`);
  if (b.levels) parts.push(`${b.levels} level${b.levels === 1 ? '' : 's'}`);
  if (b.room_effect) parts.push(b.room_effect);
  if (b.changed_settings) parts.push(`${b.changed_settings} setting${b.changed_settings === 1 ? '' : 's'} changed`);
  let line = `Show: ${parts.length ? parts.join(', ') : 'on'}`;
  if (b.standdown) line += ` — standing down (${b.standdown})`;
  return line;
}

/** "3 of 4 ran — Flash did not run: no fixture called 'x'" */
export function runSummary(run: ShowRun): string {
  const ran = run.steps.filter((s) => s.status === 'applied').length;
  const total = run.steps.length;
  if (run.state === 'running') return `${run.name}: running (${ran} of ${total} so far)`;
  if (run.state === 'done') return `${run.name}: all ${total} ran`;
  if (run.state === 'refused') return `${run.name}: nothing ran — ${run.steps[0]?.detail ?? 'refused'}`;
  if (run.state === 'cancelled') return `${run.name}: ended early (${ran} of ${total} ran)`;
  const bad = run.steps.filter((s) => s.status === 'failed' || s.status === 'refused');
  const first = bad[0];
  return `${run.name}: ${ran} of ${total} ran` +
    (first ? ` — ${first.label} did not run: ${first.detail}` : '') +
    (bad.length > 1 ? ` (+${bad.length - 1} more)` : '');
}

export function endShowSummary(r: EndShowReport): string {
  const parts: string[] = [];
  if (r.restored.length) parts.push(`put back: ${r.restored.join(', ')}`);
  if (r.released_devices.length) parts.push(`${r.released_devices.length} fixture(s) back to the show`);
  if (r.room_effect_stopped) parts.push('room effect stopped');
  if (r.left_alone.length) parts.push(`left as you have it: ${r.left_alone.map((x) => x.label).join(', ')}`);
  if (r.failed.length) parts.push(`could not put back: ${r.failed.map((x) => x.label).join(', ')}`);
  return parts.length ? `Show ended — ${parts.join('; ')}` : 'Show ended — nothing to put back';
}

/** Help topics the SERVED catalogue names per action kind (each kind's
 * `help_topic`, spectra/services/show_actions.py) and the page renders as
 * HelpLinks — listed here so the help-orphan audit (a grep of .ts/.tsx for
 * each id) can see they are linked. Keep in step with show_actions.py. */
export const SHOW_KIND_HELP_TOPICS = [
  'show-actions', 'show-device-states', 'show-level', 'show-room-effects', 'show-sets',
  'show-arming', 'show-high-low-triggers', 'show-run-view', 'sonic-light-show',
] as const;

// ── PHASE 2: arms and the High/Low Triggers ───────────────────────────────


export const TRIGGER_LABEL: Record<ArmTrigger, string> = {
  scene_change: 'next scene change',
  high: 'next High Trigger',
  low: 'next Low Trigger',
};

export function triggerLabel(on: string): string {
  return TRIGGER_LABEL[on as ArmTrigger] ?? on.replace(/_/g, ' ');
}

/** "1:05" / "0:07" — a countdown in m:ss, never negative. */
export function mmss(ms: number): string {
  const s = Math.max(0, Math.round(ms / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

/** How long until `dueMs` on the song clock, or null when unknown. */
export function countdown(dueMs: number | null | undefined,
                          positionMs: number | null | undefined): string | null {
  if (dueMs === null || dueMs === undefined || positionMs === null || positionMs === undefined) return null;
  if (dueMs <= positionMs) return null;
  return `in ${mmss(dueMs - positionMs)}`;
}

/** One armed card's line: what, on what, how, and why it is waiting. */
export function armLine(a: ShowArm, positionMs: number | null | undefined): string {
  const parts = [`${a.label || 'Action'} → ${triggerLabel(a.on)}`];
  parts.push(a.repeat ? `repeat (${a.fire_count} so far)` : 'once');
  if (a.song_uri) parts.push(a.this_song === false ? 'this song only (not this song)' : 'this song only');
  if ((a.lead_ms ?? 0) > 0) parts.push(`starts ${((a.lead_ms ?? 0) / 1000).toFixed(1)} s early so its fade lands on the mark`);
  const cd = countdown(a.due_ms ?? null, positionMs);
  if (cd) parts.push(cd);
  if (a.last_outcome?.status === 'waiting' && a.last_outcome.reason) {
    parts.push(`waited: ${a.last_outcome.reason}`);
  }
  return parts.join(' · ');
}

/** One ended arm, for the history list. */
export function armHistoryLine(a: ShowArm): string {
  return `${a.label || 'Action'} (${triggerLabel(a.on)}): ${a.status}${a.end_reason ? ` — ${a.end_reason}` : ''}`;
}

/** "at least 0:07" / "could change any moment" — the showing scene's own
 * minimum-hold FLOOR, never a real prediction of when it actually changes. */
export function sceneChangeLine(expectedS: number | null | undefined): string {
  if (expectedS === null || expectedS === undefined) return 'unknown';
  if (expectedS <= 0) return 'could change any moment';
  return `at least ${mmss(expectedS * 1000)}`;
}

/** The High/Low line for this song: where it sits and why. */
export function cueLine(c: ShowCue | null, positionMs: number | null | undefined): string {
  if (!c) return 'none on this song';
  const why = c.source === 'moved' ? 'moved by you'
    : c.source === 'drop_mark' ? 'your drop mark' : 'automatic';
  const cd = countdown(c.timestamp_ms, positionMs);
  const close = c.runner_up_close && c.source === 'auto' ? ' · a runner-up is within 10%' : '';
  return `${mmss(c.timestamp_ms)} (${why})${cd ? ` · ${cd}` : ' · passed'}${close}`;
}
