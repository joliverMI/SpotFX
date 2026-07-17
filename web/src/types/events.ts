/**
 * TypeScript mirror of models/music_event.py.
 * Keep field names/defaults in sync with the pydantic models — the editor
 * round-trips whole MusicEvent JSON through POST /api/events (upsert).
 */

// ── Value bindings (signal-driven parameters) ───────────────────────────────

export type SignalName = 'rms_total' | 'rms_bass' | 'onset_score' | 'section_energy' | 'trigger_intensity';

export interface BindingStep {
  threshold: number;              // applies when signal >= threshold
  value: number | boolean | string;
}

export interface ValueBinding {
  bind: 'signal';
  signal: SignalName;
  window_beats: number;           // 0 = nearest beat; N = rolling mean over N beats
  window_dir: 'past' | 'future' | 'centered';
  mode: 'map' | 'steps';
  in_min: number;
  in_max: number;
  out_min: number;
  out_max: number;
  steps: BindingStep[];
  fallback: number | boolean | string | null;
}

export type Bindable<T> = T | ValueBinding;

export const isBinding = (v: unknown): v is ValueBinding =>
  typeof v === 'object' && v !== null && (v as ValueBinding).bind === 'signal';

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
  number?: Bindable<number> | null;
  scale_overrides?: Record<string, number> | null;
  color_kind?: 'gradient' | 'solid' | null;
  color_value?: string | null;
  bg_color?: string | null;
  accent_color?: string | null;
  polygon?: Bindable<boolean | 'toggle'> | null;
  star?: Bindable<number> | null;
  edges?: Bindable<number> | null;
  twist?: Bindable<number> | null;
  flip?: Bindable<boolean | 'toggle'> | null;
  x_offset?: Bindable<number> | null;
  y_offset?: Bindable<number> | null;
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
  ramp_ms: Bindable<number> | null;
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

export interface LedFxGlobalTransitionAction extends ActionBase {
  type: 'ledfx_global_transition';
  transition_time: number;
  transition_mode: string | null;
}

export interface EffectParamChange {
  param_label: string;
  target_value: Bindable<number>;
  toggle_action: Bindable<string> | null;
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
  ramp_ms: Bindable<number> | null;
}

export interface MorphStepAction extends ActionBase {
  type: 'morph_step';
  name?: string; // optional editor display name, shown in summaries/previews
  ramp_ms: Bindable<number> | null;
  intensity_source: IntensitySource;
  targets: MorphTarget[];
}

export interface SetColorAction extends ActionBase {
  type: 'set_color';
  ref_id: string;
  pick_mode: 'default' | 'cycle' | 'weighted';
  advance: Bindable<number>;
  direction: 'forward' | 'backward';
  ramp_ms: Bindable<number> | null;
  preserve_effect: boolean;
}

/** Rotate every showing color (FG/BG/accent) around the hue wheel. */
export interface MorphColorAction extends ActionBase {
  type: 'morph_color';
  scope: MorphScope;              // empty = inherit nearest Target, else global
  degrees: number;                // default 180 = complementary contrast
  direction: 'forward' | 'backward';
  ramp_ms: Bindable<number> | null;
  intensity_scale: number;        // 0 = ignore beat intensity
  intensity_source: IntensitySource;
  preserve_melt_bg: boolean;      // true = keep melt BG; power BG always rotates
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

/** HA choose-style random container. */
export interface RandomOption {
  id: string;
  name: string;
  labels: string[];
  weight: number;
  /** Eligible only when trigger energy >= floor (null = no floor). */
  energy_floor?: number | null;
  /** Eligible only when trigger energy <= ceiling (null = no ceiling). */
  energy_ceiling?: number | null;
  /** -1..1 weight tilt across the floor..ceiling window; 0 = flat. */
  energy_scale?: number;
  scope: MorphScope | null; // null = inherit group Target
  actions: Action[];
}

export interface RandomGroupAction extends ActionBase {
  type: 'random_group';
  id: string;
  dedupe: boolean;
  scope: MorphScope | null; // default Target for options
  options: RandomOption[];
}

/** Unified revert for sequence_group — ms mode reads delay_ms, beats mode delay_beats+pre_ramp. */
export interface GroupRevert {
  enabled: boolean;
  delay_ms: number;
  delay_beats: number;
  transition_ms: number;
  pre_ramp: boolean;
}

export interface SequenceChild {
  id: string;
  name: string;
  labels: string[];
  delay_ms: number;    // ms mode: slept before this child (honored on child 0)
  delay_beats: number; // beats mode: extra beats skipped (ignored on child 0)
  pre_ramp: boolean;   // beats mode only
  scope: MorphScope | null; // null = inherit group Target
  actions: Action[];   // fire concurrently
}

export interface SequenceGroupAction extends ActionBase {
  type: 'sequence_group';
  id: string;
  timing: 'ms' | 'beats';
  scope: MorphScope | null; // default Target for children (empty leaf scopes adopt it)
  children: SequenceChild[];
  revert: GroupRevert | null;
  beat_fallback: 'skip' | 'fallback';
  start_offset_beats: number;
}

export interface ParallelChild {
  id: string;
  name: string;
  labels: string[];
  offset_ms: number; // stagger vs group fire moment (negative = earlier)
  scope: MorphScope | null; // per-lane Target
  actions: Action[];
}

export interface ParallelGroupAction extends ActionBase {
  type: 'parallel_group';
  id: string;
  children: ParallelChild[];
}

export type Action =
  | EventRefAction
  | LedFxSceneAction
  | LedFxAmbientAction
  | LedFxAmbientColorAction
  | LedFxGlobalTransitionAction
  | LedFxEffectParamAction
  | MorphStepAction
  | SetColorAction
  | MorphColorAction
  | DeviceSettingsAction
  | RandomGroupAction
  | SequenceGroupAction
  | ParallelGroupAction;

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
  | 'device_settings' | 'composite';

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

  actions: Action[];

  sequence_steps: SequenceStep[];
  revert: RevertConfig | null;

  beat_sequence_steps: BeatSequenceStep[];
  beat_revert: BeatRevertConfig | null;
  beat_sequence_fallback: 'skip' | 'fallback';
  beat_sequence_start_offset_beats: number;

  morph_lanes: MorphLane[];

  device_targets: DeviceSettingTarget[];

  /** event_type "composite": the whole body as one Action tree (null = empty). */
  root: Action | null;

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
  composite: 'Composite',
};
