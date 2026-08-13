/** Factory defaults mirroring the pydantic model defaults in models/music_event.py. */
import type {
  Action,
  ActionType,
  BeatSequenceStep,
  IntensityLane,
  MusicEvent,
  ParallelChild,
  SequenceChild,
  SequenceStep,
} from '../types/events';
import { SCENE_GROUP_COLOR_REF } from '../types/events';
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
        ...base, type, ref_id: SCENE_GROUP_COLOR_REF, pick_mode: 'default', advance: 1,
        direction: 'forward', ramp_ms: null, preserve_effect: true, display_mode: 'default',
      };
    case 'morph_color':
      return {
        ...base, type, scope: { virtual_ids: [], categories: [], roles: [] },
        degrees: 180, direction: 'forward', ramp_ms: null,
        intensity_scale: 0, intensity_source: 'rms_total', morph_bg: true,
      };
    case 'scene_morph':
      return { ...base, type, advance: 1, direction: 'forward' };
    case 'device_settings':
      return { ...base, type, targets: [] };
    case 'brightness':
      return {
        ...base, type, scope: { virtual_ids: [], categories: [], roles: [] },
        ramp_ms: null, intensity_source: 'rms_total',
        brightness_mode: 'absolute', brightness_value: 1, brightness_nudge: null,
        bg_mode: 'keep', bg_value: null, bg_nudge: null,
      };
    case 'random_group':
      return { ...base, type, id: uuid(), dedupe: true, scope: null, options: [] };
    case 'sequence_group':
      return {
        ...base, type, id: uuid(), timing: 'ms', scope: null, children: [],
        revert: null, beat_fallback: 'fallback', start_offset_beats: 0,
      };
    case 'parallel_group':
      return { ...base, type, id: uuid(), children: [] };
    case 'intensity_chooser':
      // Starts with the default lane; threshold dots add more.
      return {
        ...base, type, id: uuid(), source: 'trigger_intensity', scope: null,
        ramp_ms: null, lanes: [newIntensityLane(0)],
      };
  }
}

export const newSequenceChild = (): SequenceChild => ({
  id: uuid(), name: '', labels: [], delay_ms: 0, delay_beats: 0, delay_updates: null,
  pre_ramp: true, scope: null, actions: [],
});

export const newParallelChild = (): ParallelChild => ({
  id: uuid(), name: '', labels: [], offset_ms: 0, scope: null, actions: [],
});

export const newIntensityLane = (threshold = 0.5): IntensityLane => ({
  id: uuid(), name: '', labels: [], threshold, scope: null, actions: [],
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
    ramp_ms: null,
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
    scene_group_members: [],
    scene_group_mode: 'cycle',
    scene_group_cycle_behavior: 'wrap',
    scene_group_exclude_current: true,
    scene_group_random_start: false,
    scene_group_color_ref_id: '',
    scene_group_dark_color_ref_id: '',
    scene_group_light_color_ref_id: '',
    display_mode: 'default',
    event_offset_ms: 0,
  };
}
