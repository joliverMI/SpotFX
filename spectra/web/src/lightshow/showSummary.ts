/** Pure wording for the Light Show's status surfaces — kept out of React so
 * scripts/check_light_show_summary.mjs can drive it with no DOM. */
import type { EndShowReport, ShowBrief, ShowRun } from './types';

/** The top-bar strip's one line, or null when the show holds nothing (the
 * strip is absent then — it costs no space in normal use). */
export function stripLine(b: ShowBrief | null | undefined): string | null {
  if (!b || !b.active) return null;
  const parts: string[] = [];
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
] as const;
