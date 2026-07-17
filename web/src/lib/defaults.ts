/** Factory defaults mirroring the pydantic model defaults in models/music_event.py. */
import type {
  Action,
  ActionType,
  BeatSequenceStep,
  MusicEvent,
  ParallelChild,
  SequenceChild,
  SequenceStep,
} from '../types/events';
import { uuid } from './uid';

export function newAction(type: ActionType): Action {
  const base = { labels: [] as string[], weight: 1.0 };
  switch (type) {
    case 'event_ref':
      return { ...base, type, event_id: '' };
    case 'ledfx_scene':
      return { ...base, type, scene_id: '' };
    case 'ledfx_ambient':
      return {
        ...base, type,
        color: null, brightness: null, max_brightness: null,
        blur: null, bass_decay_rate: null, background_brightness: null,
      };
    case 'ledfx_ambient_color':
      return { ...base, type };
    case 'ledfx_global_transition':
      return { ...base, type, transition_time: 0.5, transition_mode: null };
    case 'ledfx_effect_param':
      return { ...base, type, virtual_id: null, category: null, params: [], ramp_ms: null };
    case 'morph_step':
      return { ...base, type, name: '', ramp_ms: null, intensity_source: 'rms_total', targets: [] };
    case 'set_color':
      return {
        ...base, type, ref_id: '', pick_mode: 'default', advance: 1,
        direction: 'forward', ramp_ms: null, preserve_effect: true,
      };
    case 'morph_color':
      return {
        ...base, type, scope: { virtual_ids: [], categories: [], roles: [] },
        degrees: 180, direction: 'forward', ramp_ms: null,
        intensity_scale: 0, intensity_source: 'rms_total', preserve_melt_bg: false,
      };
    case 'device_settings':
      return { ...base, type, targets: [] };
    case 'random_group':
      return { ...base, type, id: uuid(), dedupe: true, scope: null, options: [] };
    case 'sequence_group':
      return {
        ...base, type, id: uuid(), timing: 'ms', scope: null, children: [],
        revert: null, beat_fallback: 'fallback', start_offset_beats: 0,
      };
    case 'parallel_group':
      return { ...base, type, id: uuid(), children: [] };
  }
}

export const newSequenceChild = (): SequenceChild => ({
  id: uuid(), name: '', labels: [], delay_ms: 0, delay_beats: 0, pre_ramp: true, scope: null, actions: [],
});

export const newParallelChild = (): ParallelChild => ({
  id: uuid(), name: '', labels: [], offset_ms: 0, scope: null, actions: [],
});

export const newSequenceStep = (): SequenceStep => ({
  step_type: 'action',
  event_id: null,
  action: null,
  actions: [],
  delay_ms: 0,
  labels: [],
});

export const newBeatSequenceStep = (): BeatSequenceStep => ({
  step_type: 'action',
  event_id: null,
  action: null,
  actions: [],
  delay_beats: 0,
  pre_ramp: true,
  labels: [],
});

export function newEvent(event_type: MusicEvent['event_type'] = 'single'): MusicEvent {
  return {
    id: uuid(),
    name: 'New Event',
    event_type,
    color: '#FFD700',
    labels: [],
    energy_level: null,
    ai_exposed: false,
    fixed: false,
    scene_override: false,
    actions: [],
    sequence_steps: [],
    revert: null,
    beat_sequence_steps: [],
    beat_revert: null,
    beat_sequence_fallback: 'fallback',
    beat_sequence_start_offset_beats: 0,
    morph_lanes: [],
    device_targets: [],
    root: null,
    event_offset_ms: 0,
  };
}
