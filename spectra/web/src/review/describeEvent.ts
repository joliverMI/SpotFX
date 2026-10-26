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
  absorb: 'Absorb Music',
};

export const BUCKET_COLOR: Record<ReviewEventItem['bucket'], string> = {
  scenes: '#a855f7',
  responses: '#f59e0b',
  color_sets: '#14b8a6',
  triggers: '#60a5fa',
  deferred: '#94a3b8',
  watchdog: '#64748b',
  show: '#f472b6',
  absorb: '#38bdf8',
};

/** engine._response_gate/_update_gate's refusal words, as a reader says them.
 * An unlisted reason is shown verbatim rather than guessed at. */
const KIND_BATCH_SKIP_REASON: Record<string, string> = {
  preview: 'a Preview held the room',
  absorb: 'Absorb Music held the lights',
  scene_change_mode: 'scene-change mode closed',
};

/** THE DROP COLOUR CHANGE (spectra/services/drop_colour.py): why a drop's
 * colour did not change — the hold the record names, as a reader says it.
 * An unlisted word is shown verbatim rather than guessed at. */
const DROP_COLOUR_HOLD: Record<string, string> = {
  force_color: 'Force Colour holds the colours',
  gradient_drift: 'the 2D gradient made its own drop change',
  house_mode: 'a house mode keeps its own look',
  preview: 'a Preview held the room',
  absorb: 'Absorb Music held the lights',
  paused: 'the room is paused',
  dinner_party: 'Dinner Party holds the room',
  ambient: 'Hue Hold holds the room',
  scene_change_mode: 'scene-change mode closed',
};

/** ...and why the set it landed was the one picked (the pick's rung). */
const DROP_COLOUR_RUNG: Record<string, string> = {
  band: '',
  no_hue_yet: '',
  to_rainbow: ', a rainbow',
  from_rainbow: ', from a rainbow',
  rainbow_only: ', rainbow to rainbow (nothing else allowed)',
  widest_available: ', the farthest set allowed (none 150-210° away)',
  pinned_group: ', the pinned group\'s next set',
};

/** THE DROP COLOUR CHANGE's outcome as a drop's own entry carries it
 * (trigger_engine.drop_colour_brief): to which set, how far round the wheel
 * and why — or what held it. Empty when the entry has none. */
export function describeDropColour(c: Record<string, unknown> | undefined): string {
  if (!c) return '';
  const result = c.result as string | undefined;
  if (result === 'faded_at_pre_drop') {
    const inner = describeDropColour(c.pre_drop as Record<string, unknown> | undefined);
    return inner ? `${inner} (at its pre-drop)` : ' · colour already changed at its pre-drop';
  }
  if (result === 'jumped') {
    const to = (c.to_set_name as string | undefined) ?? (c.to_set_id as string | undefined) ?? 'a new set';
    const dist = c.distance_deg as number | undefined;
    const why = DROP_COLOUR_RUNG[(c.rung as string | undefined) ?? ''] ?? `, ${String(c.rung)}`;
    const how = c.moment === 'pre_drop' ? ', fading to the drop' : '';
    return ` · new colours: ${to}${dist != null ? ` (${Math.round(dist)}° away)` : ''}${why}${how}`;
  }
  if (result === 'held') {
    const held = (c.held_for as string | undefined) ?? 'held';
    return ` · colours held (${DROP_COLOUR_HOLD[held] ?? held})`;
  }
  if (result === 'kept_current') return ' · colours kept (no other set allowed)';
  if (result === 'off') return '';
  return result ? ` · colour change: ${result}` : '';
}

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
      if (d.via === 'drop_colour') {
        // engine.fire_drop_colour_event: the drop colour change landed.
        const dist = d.distance_deg as number | undefined;
        const how = d.moment === 'pre_drop' ? ', faded across the pre-drop' : '';
        return `Colour set: ${name} (drop colour change${dist != null ? `, ${Math.round(dist)}° away` : ''}${how})`;
      }
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
              // THE FIREWORKS MELDS: Fireworks played its own drop first
              : d.at === 'after_drop' ? 'just after its own drop'
                : d.at === 'next_hit' ? 'on the next big bass hit after its own drop'
                  : d.at === 'deadline' ? 'at the deadline (no big hit came after its own drop)'
                    : d.at === 'before_next_sequence' ? 'as the next drop sequence began'
                      : 'at the charge';
        const res = d.result === 'switched' ? '' : ` — not cut (${(d.skipped as string | undefined) ?? d.result})`;
        return `Drop switched the scene to ${to}, a hard cut ${when}${res}`;
      }
      const colour = describeDropColour(d.drop_colour as Record<string, unknown> | undefined);
      if (d.drop_sequence && d.member === 'pre_drop') {
        // THE DROP COLOUR CHANGE starting its fade on a pre-drop.
        return `Drop sequence: colour change at the pre-drop${colour}`;
      }
      if (d.drop_sequence) {
        // A drop-sequence member (spectra/services/drop_firing.py) — the
        // ordinary charge/lull/drop response, not a stored trigger.
        const member = (d.member as string | undefined) ?? item.key.split(':')[1];
        const whose = d.his ? 'yours' : 'detected';
        const intensity = d.intensity as number | undefined;
        return `Drop sequence: ${member} (${whose})${intensity != null ? ` @ ⚡${intensity.toFixed(2)}` : ''}${colour}`;
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
      return `Trigger fired: ${kind}${source ? ` (${source})` : ''}${snapNote}${colour}`;
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
      if (d.reason === 'absorb') {
        // spectra/services/absorb_hold.py: an Absorb Music window kept the
        // lights still while it played songs nobody was hearing.
        const what = (d.scene_name as string | undefined)
          ?? (d.event_class as string | undefined) ?? item.key;
        return `Held for Absorb Music (the house is silent): ${what}`;
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
    case 'absorb':
      return item.key === 'held'
        ? 'Absorb Music: the house went silent; the lights hold still'
        : 'Absorb Music: the house is back; the lights are free';
    default:
      return `${BUCKET_LABEL[item.bucket] ?? item.bucket}: ${item.key}`;
  }
}
