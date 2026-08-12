/** Per-level editor Preview — fire an unsaved action subtree immediately via
 * POST /api/events/preview. Group children (lanes, steps, options, morph
 * lanes) are wrapped back into a single-child copy of their parent group so
 * the backend fires them with the exact group semantics, minus anything that
 * would defer or gate the fire (delays, offsets, energy windows, revert). */
import { apiPost } from '../api/client';
import { stripUids, uuid } from './uid';
import type {
  Action, IntensityChooserAction, IntensityLane, MorphLane, MusicEvent,
  ParallelChild, RandomGroupAction, RandomOption,
  SequenceChild, SequenceGroupAction, SequenceStep,
} from '../types/events';

async function fire(body: { action?: Action; event?: MusicEvent }): Promise<void> {
  await apiPost('/events/preview', stripUids(body));
}

/** Preview a single action card (any level, including a whole group card). */
export const previewAction = (action: Action) => fire({ action });

/** Preview a full (possibly unsaved / dirty) event draft. */
export const previewEvent = (event: MusicEvent) => fire({ event });

/** Preview one parallel-group lane: fire it now, ignoring its stagger offset. */
export const previewParallelChild = (child: ParallelChild) =>
  fire({
    action: {
      type: 'parallel_group', id: uuid(), labels: [], weight: 1,
      children: [{ ...child, offset_ms: 0 }],
    },
  });

/** Preview one sequence-group step: keep group scope/timing semantics but fire
 * immediately (delays zeroed) and skip the group's revert. */
export const previewSequenceChild = (group: SequenceGroupAction, child: SequenceChild) =>
  fire({
    action: {
      ...group, id: uuid(), revert: null, start_offset_beats: 0,
      children: [{ ...child, delay_ms: 0, delay_beats: 0, delay_updates: null }],
    },
  });

/** Preview one random-group option: force the pick, ignoring energy gating. */
export const previewRandomOption = (group: RandomGroupAction, opt: RandomOption) =>
  fire({
    action: {
      ...group, id: uuid(), dedupe: false,
      options: [{ ...opt, weight: 1, energy_floor: null, energy_ceiling: null, energy_scale: 0 }],
    },
  });

/** Preview one intensity-chooser lane: force the pick by making it the sole
 * (default) lane — manual test fires carry no intensity, which selects the
 * default lane, i.e. this one. */
export const previewIntensityLane = (group: IntensityChooserAction, lane: IntensityLane) =>
  fire({
    action: { ...group, id: uuid(), lanes: [{ ...lane, threshold: 0 }] },
  });

/** Preview a morph_set / scene_update lane: one weighted pick among its
 * alternatives, fired immediately (lane offset ignored). */
export const previewMorphLane = (lane: MorphLane) =>
  fire({
    action: {
      type: 'random_group', id: uuid(), labels: [], weight: 1, dedupe: false, scope: null,
      options: lane.alternatives.map((a) => ({
        id: uuid(), name: '', labels: [], weight: a.weight ?? 1,
        energy_floor: null, energy_ceiling: null, energy_scale: 0,
        scope: null, actions: [a],
      })),
    },
  });

/** Preview a top-level sequence step (event ref or concurrent action list). */
export const previewSequenceStep = (step: SequenceStep) => {
  if (step.step_type === 'event') {
    if (!step.event_id) return Promise.reject(new Error('No event picked'));
    return fire({ action: { type: 'event_ref', event_id: step.event_id, labels: [], weight: 1 } });
  }
  return fire({
    action: {
      type: 'parallel_group', id: uuid(), labels: [], weight: 1,
      children: [{ id: uuid(), name: '', labels: step.labels ?? [], offset_ms: 0, scope: null, actions: step.actions }],
    },
  });
};
