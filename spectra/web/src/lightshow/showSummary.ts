/** Pure wording for the Light Show's status surfaces — kept out of React so
 * scripts/check_light_show_summary.mjs can drive it with no DOM. */
import type { IconName } from '../components/iconRegistry';
import type {
  ArmsStatus, ArmTrigger, EndShowReport, SequenceRun, ShowArm, ShowBrief, ShowCue, ShowRun,
} from './types';

/** The top-bar strip's one line, or null when the show holds nothing (the
 * strip is absent then — it costs no space in normal use). */
export function stripLine(b: ShowBrief | null | undefined): string | null {
  if (!b || !b.active) return null;
  const parts: string[] = [];
  if (b.armed) parts.push(`${b.armed} armed`);
  if (b.running_sets) parts.push(`${b.running_sets} running`);
  if (b.holds) parts.push(`${b.holds} holding`);
  if (b.levels) parts.push(`${b.levels} level${b.levels === 1 ? '' : 's'}`);
  if (b.pulse_mods) parts.push(`${b.pulse_mods} Pulse hold${b.pulse_mods === 1 ? '' : 's'}`);
  if (b.flare_blocks) parts.push(`flares off ×${b.flare_blocks}`);
  if (b.room_effect) parts.push(b.room_effect);
  if (b.changed_settings) parts.push(`${b.changed_settings} setting${b.changed_settings === 1 ? '' : 's'} changed`);
  if (b.playlist) parts.push(`following ${b.playlist.name}`);
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
  if (r.ended_pulse_mods) parts.push(`${r.ended_pulse_mods} Pulse hold(s) ended`);
  if (r.ended_flare_blocks) parts.push('flares back on');
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
  'show-pulse', 'show-flares', 'show-playlists', 'show-playlist-steps', 'show-playlist-run',
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
  if (a.tag) parts.push(a.tag);
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

// ── THE BAR SLOT: current → next (UI declutter plan §3) ───────────────────

const TRIGGER_ICON: Record<ArmTrigger, IconName> = {
  scene_change: 'rabbit', high: 'arrowUp', low: 'arrowDown',
};

export interface ShowNowNextItem {
  icon: IconName;
  label: string;
  /** The song-position ms this item fires at, when it's a plain trigger
   * wait with a known mark (ArmsStatus's `due_ms`) — the bar slot ticks a
   * live countdown to this against the interpolated song position. `null`
   * means "no clean numeric countdown" (a sequence Wait on a song/trigger
   * count, or nothing known yet) — `whenText` is shown instead, static. */
  dueMs: number | null;
  whenText: string;
}

export interface ShowNowNext {
  current: ShowNowNextItem | null;
  next: ShowNowNextItem | null;
  /** Where tapping the slot goes. */
  href: string;
  /** The small count badge on the ◈ icon — "the show is doing something
   * to my room" (holds + levels + pulse mods + flare blocks + room
   * effect), kept (plan §13 Q13). */
  holdsCount: number;
}

function sequenceItemDisplay(run: SequenceRun, index: number): ShowNowNextItem | null {
  const item = run.items[index];
  if (!item) return null;
  if (item.kind === 'wait') {
    const w = item.wait;
    const label = item.title ?? (w ? `Wait (${w.kind})` : 'Wait');
    if (index === run.index && run.waiting_reason === 'duration' && run.wait_left_s != null) {
      return { icon: 'wait', label, dueMs: null, whenText: `${mmss(run.wait_left_s * 1000)} left` };
    }
    if (index === run.index && run.wait_count > 0) {
      return { icon: 'wait', label, dueMs: null, whenText: `${run.wait_count} more ${w?.trigger === 'scene_change' ? 'scene change' : triggerLabel(w?.trigger ?? '')}${run.wait_count === 1 ? '' : 's'}` };
    }
    return { icon: 'wait', label, dueMs: null, whenText: w ? `waiting on ${w.kind}` : 'waiting' };
  }
  const icon: IconName = item.arm === 'instant' ? 'bolt' : TRIGGER_ICON[item.arm as ArmTrigger] ?? 'bolt';
  const label = item.title ?? item.label ?? 'Set';
  const whenText = item.arm === 'instant' ? 'now' : `on ${triggerLabel(item.arm)}`;
  return { icon, label, dueMs: null, whenText };
}

function armDisplay(a: ShowArm, positionMs: number | null | undefined): ShowNowNextItem {
  const icon = TRIGGER_ICON[a.on as ArmTrigger] ?? 'bolt';
  const label = a.label || 'Action';
  const dueMs = a.due_ms ?? null;
  const cd = countdown(dueMs, positionMs);
  const whenText = cd ?? (dueMs != null ? 'now' : `on ${triggerLabel(a.on)}`);
  return { icon, label, dueMs, whenText };
}

/** The bar slot's rule, exactly as decided: a running sequence wins
 * (current/next = its own items); else the soonest-due armed actions;
 * else "Nothing armed". Tap-through: `/show?tab=sequence&sub=run` while a
 * sequence runs, else `/show?tab=run`. */
export function showNowNext(
  brief: ShowBrief | null | undefined,
  arms: ArmsStatus | null | undefined,
  sequence: { run: SequenceRun | null } | null | undefined,
): ShowNowNext {
  const holdsCount = brief
    ? (brief.holds ?? 0) + (brief.levels ?? 0) + (brief.pulse_mods ?? 0) + (brief.flare_blocks ?? 0)
      + (brief.room_effect ? 1 : 0) + (brief.running_sets ?? 0)
    : 0;

  const run = sequence?.run;
  if (run?.active) {
    const n = run.items.length;
    const current = sequenceItemDisplay(run, run.index);
    const nextIndex = run.index + 1 < n ? run.index + 1 : (run.loop && n > 0 ? 0 : -1);
    const next = nextIndex >= 0 ? sequenceItemDisplay(run, nextIndex) : null;
    return { current, next: next ?? { icon: 'wait', label: 'End', dueMs: null, whenText: '—' }, href: '/show?tab=sequence&sub=run', holdsCount };
  }

  const positionMs = arms?.song.position_ms ?? null;
  const armed = [...(arms?.armed ?? [])].sort((a, b) => {
    const ad = a.due_ms ?? Infinity;
    const bd = b.due_ms ?? Infinity;
    return ad - bd;
  });
  if (armed.length === 0) {
    return { current: null, next: null, href: '/show?tab=run', holdsCount };
  }
  const current = armDisplay(armed[0], positionMs);
  const next = armed[1] ? armDisplay(armed[1], positionMs) : null;
  return { current, next, href: '/show?tab=run', holdsCount };
}
