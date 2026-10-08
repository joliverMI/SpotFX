/** Human labels for a show-log event, read off the same `detail` shape
 * each fire_history choke point already stamps (see fire_history.py's
 * record_fire call sites) — no extra lookups needed. */
import type { ReviewEventItem } from '../types';

const BUCKET_LABEL: Record<ReviewEventItem['bucket'], string> = {
  scenes: 'Scene',
  responses: 'Response',
  color_sets: 'Colour set',
  triggers: 'Trigger',
  deferred: 'Deferred (dwell)',
  watchdog: 'Watchdog',
  show: 'Light Show',
};

export const BUCKET_COLOR: Record<ReviewEventItem['bucket'], string> = {
  scenes: '#a855f7',
  responses: '#f59e0b',
  color_sets: '#14b8a6',
  triggers: '#60a5fa',
  deferred: '#94a3b8',
  watchdog: '#64748b',
  show: '#f472b6',
};

/** engine._response_gate/_update_gate's refusal words, as a reader says them.
 * An unlisted reason is shown verbatim rather than guessed at. */
const KIND_BATCH_SKIP_REASON: Record<string, string> = {
  preview: 'a Preview held the room',
  scene_change_mode: 'scene-change mode closed',
};

export function describeEvent(item: ReviewEventItem): string {
  const d = item.detail;
  switch (item.bucket) {
    case 'scenes': {
      const name = (d.scene_name as string | undefined) ?? item.key;
      const intensity = d.intensity as number | undefined;
      return `Scene: ${name}${intensity != null ? ` @ ⚡${intensity.toFixed(2)}` : ''}`;
    }
    case 'responses': {
      const cls = (d.event_class as string | undefined) ?? item.key;
      const intensity = d.intensity as number | undefined;
      return `Response: ${cls}${intensity != null ? ` @ ⚡${intensity.toFixed(2)}` : ''}`;
    }
    case 'color_sets': {
      const name = (d.set_name as string | undefined) ?? item.key;
      // via "analysed_cue": engine.fire_analysed_color_event — a generated
      // cue's colour jump on a song with no authored trigger.
      return `Colour set: ${name}${d.via === 'analysed_cue' ? ' (analysed moment)' : ''}`;
    }
    case 'triggers': {
      if (d.drop_sequence && d.member === 'switch') {
        // THE DROP-LED SCENE SWITCH (spectra/services/drop_switch.py): the
        // cut a drop sequence made, or why it did not.
        const to = (d.to_scene as string | undefined) ?? 'another scene';
        const when = d.at === 'drop' ? 'on the drop'
          : d.at === 'charge_flare' ? 'on a flare in the charge'
            : d.at === 'charge_flare_missed' ? 'at the next member (the flare never fired)'
              : 'at the charge';
        const res = d.result === 'switched' ? '' : ` — not cut (${(d.skipped as string | undefined) ?? d.result})`;
        return `Drop switched the scene to ${to}, a hard cut ${when}${res}`;
      }
      if (d.drop_sequence) {
        // A drop-sequence member (spectra/services/drop_firing.py) — the
        // ordinary charge/lull/drop response, not a stored trigger.
        const member = (d.member as string | undefined) ?? item.key.split(':')[1];
        const whose = d.his ? 'yours' : 'detected';
        const intensity = d.intensity as number | undefined;
        return `Drop sequence: ${member} (${whose})${intensity != null ? ` @ ⚡${intensity.toFixed(2)}` : ''}`;
      }
      if (d.analysed_flare) {
        // An unselected analysed transition fired as a flare
        // (spectra/services/analysed_flares.py) — not a stored trigger.
        return 'Analysed flare (a transition that did not make the cut)';
      }
      if (d.planned_scene_cue) {
        // A planned analysed scene change fired from the plan itself — the
        // song holds no stored generated cue (spectra/services/
        // analysed_flares.py, PLANNED SCENE CHANGES FIRE TOO).
        return 'Analysed scene change (planned, not a stored trigger)';
      }
      const kind = (d.action_kind as string | undefined) ?? item.key;
      const source = d.source as string | undefined;
      const snapGrid = d.snap_grid as string | undefined;
      const snapMoved = d.snap_moved_ms as number | undefined;
      const snapNote = snapGrid
        ? ` · moved to ${snapGrid} (${snapMoved != null && snapMoved >= 0 ? '+' : ''}${snapMoved ?? 0}ms)`
        : '';
      return `Trigger fired: ${kind}${source ? ` (${source})` : ''}${snapNote}`;
    }
    case 'deferred': {
      if (item.key === 'drop_window') {
        // trigger_engine held an analysed scene change or flare out of a
        // drop sequence's protected window (drop_firing.py).
        const what = (d.what as string | undefined) ?? 'analysed event';
        return `Kept clear of a drop sequence: ${what}${d.window_source === 'yours' ? ' (your own charge/lull/drop)' : ''}`;
      }
      if (item.key === 'kind_batch') {
        // A staggered flare-kind batch that woke to a refused show gate
        // (engine._run_kind_batch) — not a dwell hold, so it names its own
        // cause instead of borrowing the dwell wording below.
        const reason = d.reason as string | undefined;
        const why = (reason && KIND_BATCH_SKIP_REASON[reason]) ?? reason ?? 'unknown reason';
        const names = d.kind_names as string[] | undefined;
        const delay = d.delay_ms as number | undefined;
        return `Flare kinds skipped (${why}): ${names?.length ? names.join(', ') : item.key}${delay != null ? `, +${delay}ms` : ''}`;
      }
      const name = (d.scene_name as string | undefined) ?? item.key;
      const remaining = d.remaining_dwell_s as number | undefined;
      const result = d.update_result as string | undefined;
      return `Held (minimum dwell): ${name}${remaining != null ? `, ${remaining.toFixed(1)}s left` : ''}${result ? ` — update: ${result}` : ''}`;
    }
    case 'show': {
      // spectra/services/show_actions.py (each step a set ran, End show)
      // and show_arms.py (arm_armed / arm_fired / arm_missed / ...).
      const set = d.set as string | undefined;
      if (item.key.startsWith('arm_')) {
        const what = item.key.slice(4);
        const on = (d.on as string | undefined)?.replace('_', ' ');
        const reason = d.reason as string | undefined;
        return `Light Show: ${set ?? 'a set'} ${what}${on ? ` (on ${on})` : ''}${reason ? ` — ${reason}` : ''}`;
      }
      if (item.key === 'end_show') return 'Light Show: End show';
      const step = d.step as string | undefined;
      const detail = d.detail as string | undefined;
      return `Light Show: ${set ?? ''}${step ? ` · ${step}` : ''}${detail ? ` — ${detail}` : ''}`;
    }
    default:
      return `${BUCKET_LABEL[item.bucket] ?? item.bucket}: ${item.key}`;
  }
}
