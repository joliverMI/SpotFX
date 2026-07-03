/**
 * TypeScript mirror of models/music_event.py.
 * Keep field names/defaults in sync with the pydantic models — the editor
 * round-trips whole MusicEvent JSON through POST /api/events (upsert).
 */

// ── Morph primitives ────────────────────────────────────────────────────────

export interface MorphScope {
  virtual_ids: string[];
  categories: string[];
  roles: string[];
}

export interface NumericNudge {
  amount: number;
  scale: number;
  wrap: boolean;
  lo: number | null;
  hi: number | null;
}

export interface AspectValue {
  number?: number | null;
  scale_overrides?: Record<string, number> | null;
  color_kind?: 'gradient' | 'solid' | null;
  color_value?: string | null;
  bg_color?: string | null;
  accent_color?: string | null;
  polygon?: boolean | 'toggle' | null;
  star?: number | null;
  edges?: number | null;
  twist?: number | null;
  flip?: boolean | 'toggle' | null;
  x_offset?: number | null;
  y_offset?: number | null;
  effect_type?: string | null;
  star_nudge?: NumericNudge | null;
  edges_nudge?: NumericNudge | null;
  twist_nudge?: NumericNudge | null;
  x_offset_nudge?: NumericNudge | null;
  y_offset_nudge?: NumericNudge | null;
}

export type MorphAspect =
  | 'shape' | 'effect' | 'color' | 'bg_color' | 'reactivity' | 'brightness' | 'blur';

export type IntensitySource = 'rms_total' | 'rms_bass' | 'onset_score';

export interface MorphTarget {
  scope: MorphScope;
  aspect: MorphAspect;
  mode: 'absolute' | 'nudge';
  absolute_value: AspectValue;
  nudge_amount: number;
  intensity_scale: number;
  intensity_source: IntensitySource; // legacy, ignored at fire time
  ramp_ms: number | null;
}

// ── Actions (discriminated union on `type`) ─────────────────────────────────

interface ActionBase {
  labels: string[];
  weight: number;
}

export interface EventRefAction extends ActionBase {
  type: 'event_ref';
  event_id: string;
}

export interface LedFxSceneAction extends ActionBase {
  type: 'ledfx_scene';
  scene_id: string;
}

export interface LedFxAmbientAction extends ActionBase {
  type: 'ledfx_ambient';
  color: string | null;
  brightness: number | null;
  max_brightness: number | null;
  blur: number | null;
  bass_decay_rate: number | null;
  background_brightness: number | null;
}

export interface LedFxAmbientColorAction extends ActionBase {
  type: 'ledfx_ambient_color';
}

export interface LedFxGlobalBrightnessAction extends ActionBase {
  type: 'ledfx_global_brightness';
  brightness: number;
  ramp_ms: number | null;
}

export interface LedFxGlobalTransitionAction extends ActionBase {
  type: 'ledfx_global_transition';
  transition_time: number;
  transition_mode: string | null;
}

export interface EffectParamChange {
  param_label: string;
  target_value: number;
  toggle_action: string | null;
  string_value: string | null;
  flip_sign: boolean;
  polar_angle: number | null;
  polar_radius: number | null;
  move_x: number | null;
  move_y: number | null;
  move_angle: number | null;
  move_radius: number | null;
}

export interface LedFxEffectParamAction extends ActionBase {
  type: 'ledfx_effect_param';
  virtual_id: string | null;
  category: string | null;
  params: EffectParamChange[];
  ramp_ms: number | null;
}

export interface MorphStepAction extends ActionBase {
  type: 'morph_step';
  ramp_ms: number | null;
  intensity_source: IntensitySource;
  targets: MorphTarget[];
}

export interface MorphColorAction extends ActionBase {
  type: 'morph_color';
  ref_id: string;
  pick_mode: 'default' | 'cycle' | 'weighted';
  advance: number;
  direction: 'forward' | 'backward';
  ramp_ms: number | null;
  preserve_effect: boolean;
}

export interface DeviceSettingTarget {
  scope: MorphScope;
  max_brightness: number | null;
  frequency_min: number | null;
  frequency_max: number | null;
}

export interface DeviceSettingsAction extends ActionBase {
  type: 'device_settings';
  targets: DeviceSettingTarget[];
}

/** HA choose-style random container (backend lands in Phase C). */
export interface RandomOption {
  id: string;
  name: string;
  labels: string[];
  weight: number;
  actions: Action[];
}

export interface RandomGroupAction extends ActionBase {
  type: 'random_group';
  id: string;
  dedupe: boolean;
  options: RandomOption[];
}

export type Action =
  | EventRefAction
  | LedFxSceneAction
  | LedFxAmbientAction
  | LedFxAmbientColorAction
  | LedFxGlobalBrightnessAction
  | LedFxGlobalTransitionAction
  | LedFxEffectParamAction
  | MorphStepAction
  | MorphColorAction
  | DeviceSettingsAction
  | RandomGroupAction;

export type ActionType = Action['type'];

// ── Containers ──────────────────────────────────────────────────────────────

export interface MorphLane {
  name: string;
  labels: string[];
  alternatives: Action[];
  offset_ms: number;
}

export interface SequenceStep {
  step_type: 'event' | 'action';
  event_id: string | null;
  action: Action | null; // legacy single-action field
  actions: Action[];     // multi-action: all fire concurrently
  delay_ms: number;
  labels: string[];
}

export interface RevertConfig {
  enabled: boolean;
  delay_ms: number;
  transition_ms: number;
}

export interface BeatSequenceStep {
  step_type: 'event' | 'action';
  event_id: string | null;
  action: Action | null;
  actions: Action[];
  delay_beats: number;
  pre_ramp: boolean;
  labels: string[];
}

export interface BeatRevertConfig {
  enabled: boolean;
  delay_beats: number;
  transition_ms: number;
  pre_ramp: boolean;
}

export type EventType =
  | 'single' | 'sequence' | 'beat_sequence' | 'morph_set'
  | 'scene_update' | 'update_scene' | 'reset_scene'
  | 'shape_flare' | 'color_flare' | 'combo_flare'
  | 'device_settings';

export interface MusicEvent {
  id: string;
  name: string;
  event_type: EventType;
  color: string;
  labels: string[];
  energy_level: number | null;
  ai_exposed: boolean;
  fixed: boolean;
  scene_override: boolean;

  pre_brightness_enabled: boolean;
  pre_brightness_value: number;
  pre_brightness_ramp_ms: number | null;
  pre_transition_enabled: boolean;
  pre_transition_value: number;

  actions: Action[];

  sequence_steps: SequenceStep[];
  revert: RevertConfig | null;

  beat_sequence_steps: BeatSequenceStep[];
  beat_revert: BeatRevertConfig | null;
  beat_sequence_fallback: 'skip' | 'fallback';
  beat_sequence_start_offset_beats: number;

  morph_lanes: MorphLane[];

  device_targets: DeviceSettingTarget[];

  event_offset_ms: number;
}

/** Scene-family event types that render as morph lanes. */
export const SCENE_EVENT_TYPES: EventType[] = [
  'scene_update', 'update_scene', 'reset_scene',
  'shape_flare', 'color_flare', 'combo_flare',
];

export const EVENT_TYPE_LABELS: Record<EventType, string> = {
  single: 'Single',
  sequence: 'Sequence',
  beat_sequence: 'Beat Sequence',
  morph_set: 'Morph Set',
  scene_update: 'Scene Update',
  update_scene: 'Update Scene',
  reset_scene: 'Reset Scene',
  shape_flare: 'Shape Flare',
  color_flare: 'Color Flare',
  combo_flare: 'Combo Flare',
  device_settings: 'Device Settings',
};
