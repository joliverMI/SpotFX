/**
 * TypeScript mirror of models/music_event.py.
 * Keep field names/defaults in sync with the pydantic models — the editor
 * round-trips whole MusicEvent JSON through POST /api/events (upsert).
 */

// ── Value bindings (signal-driven parameters) ───────────────────────────────

export type SignalName = 'rms_total' | 'rms_bass' | 'onset_score' | 'section_energy' | 'trigger_intensity' | 'random';

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
  /** Numeric results get their sign flipped 50% of the time (per fire). */
  random_sign: boolean;
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
  /** Magnitude in abstract 0..1 space (negative ok); bindable (⚡/🎲). */
  amount: number | ValueBinding;
  scale: number;
  /** Flip the delta's sign 50% of the time — nudge randomly up or down. */
  random_sign: boolean;
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
  // blackhole/orbits shape sub-fields (ignored by effects without the params)
  swirl?: Bindable<number> | null;
  horizon_scale?: Bindable<number> | null;
  radius_scale?: Bindable<number> | null;
  blob_size?: Bindable<number> | null;
  reverse?: Bindable<boolean | 'toggle'> | null;
  star_nudge?: NumericNudge | null;
  edges_nudge?: NumericNudge | null;
  twist_nudge?: NumericNudge | null;
  x_offset_nudge?: NumericNudge | null;
  y_offset_nudge?: NumericNudge | null;
  swirl_nudge?: NumericNudge | null;
  horizon_scale_nudge?: NumericNudge | null;
  radius_scale_nudge?: NumericNudge | null;
  blob_size_nudge?: NumericNudge | null;
  // Per-param Reactivity sub-fields, keyed by raw LedFX param name. Values are
  // in the param's OWN range (not 0..1); toggle params take the tri-state.
  // Set = write, absent = ignore, binding = variable; *_nudges drive the
  // per-param nudge math when the target's mode is "nudge".
  reactivity_values?: Record<string, Bindable<number | boolean | 'toggle'>> | null;
  reactivity_nudges?: Record<string, NumericNudge> | null;
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
  // If set: fire as a full-config POST with LedFX server-side fallback — the
  // prior effect auto-restores after this many seconds (flare bursts).
  fallback_s?: number | null;
}

export interface MorphStepAction extends ActionBase {
  type: 'morph_step';
  name?: string; // optional editor display name, shown in summaries/previews
  ramp_ms: Bindable<number> | null;
  intensity_source: IntensitySource;
  targets: MorphTarget[];
}

/** SetColorAction.ref_id sentinels — resolved to a real Color Group at fire
 *  time: the active Scene Group's designated group / the last group fired. */
export const SCENE_GROUP_COLOR_REF = '__scene_group__';
export const CURRENT_COLOR_GROUP_REF = '__current__';

/** Dark/Light display mode — 'default' defers to the next level down the
 *  cascade (TopBar → trigger → scene group → scene → set_color → color group
 *  → color set); the first non-default level wins. Dark forces backgrounds
 *  black on non-shielded devices; light backfills the default light bg. */
export type DisplayMode = 'default' | 'dark' | 'light';

export const DISPLAY_MODE_OPTIONS = [
  { value: 'default', label: 'Default (defer)' },
  { value: 'dark', label: '🌙 Dark' },
  { value: 'light', label: '☀️ Light' },
];

export interface SetColorAction extends ActionBase {
  type: 'set_color';
  /** ColorSetCard id, or SCENE_GROUP_COLOR_REF / CURRENT_COLOR_GROUP_REF */
  ref_id: string;
  pick_mode: 'default' | 'cycle' | 'weighted';
  advance: Bindable<number>;
  direction: 'forward' | 'backward';
  ramp_ms: Bindable<number> | null;
  preserve_effect: boolean;
  /** Level 5 of the display-mode cascade (above the color cards). */
  display_mode: DisplayMode;
}

/** Rotate every showing color (FG/BG/accent) around the hue wheel. */
export interface MorphColorAction extends ActionBase {
  type: 'morph_color';
  scope: MorphScope;              // empty = inherit nearest Target, else global
  degrees: number | ValueBinding; // default 180 = complementary contrast; bindable (⚡/🎲, ± flips direction)
  direction: 'forward' | 'backward';
  ramp_ms: Bindable<number> | null;
  intensity_scale: number;        // 0 = ignore beat intensity
  intensity_source: IntensitySource;
  morph_bg: boolean;              // true (default) = BG rotates too; false = FG/accent only
}

/** Step the ACTIVE Scene Group ±advance members and fire the result.
 *  No group reference — acts on the last-fired / forced group; no-op when
 *  none is active or Force Scene pins a single scene. advance 0 = re-fire
 *  the current member (its Rest lane). */
export interface SceneMorphAction extends ActionBase {
  type: 'scene_morph';
  advance: number;
  direction: 'forward' | 'backward';
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

/** Per-parameter mode of a BrightnessAction: leave the multiplier alone,
 *  set it to a value ("change"), or add a nudge delta to it. */
export type BrightnessMode = 'keep' | 'absolute' | 'nudge';

/** Set/nudge the per-device brightness MULTIPLIERS (fg + bg, 0..1, default 1).
 *  They multiply with whatever brightness the Color Set/Group pipeline writes
 *  (final = entry value × multiplier) and re-apply immediately to the scoped
 *  devices' current effects. Reset to 1.0 on track change. */
export interface BrightnessAction extends ActionBase {
  type: 'brightness';
  scope: MorphScope;                 // empty = inherit nearest Target, else global
  ramp_ms: Bindable<number> | null;  // null = settings default; 0 = instant
  intensity_source: IntensitySource; // shared by both nudges' intensity scale
  brightness_mode: BrightnessMode;
  brightness_value: Bindable<number> | null; // 0..1 multiplier target (absolute)
  brightness_nudge: NumericNudge | null;
  bg_mode: BrightnessMode;
  bg_value: Bindable<number> | null;         // 0..1 multiplier target (absolute)
  bg_nudge: NumericNudge | null;
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
  /** ms mode only: also fire after this many scene-family fires (scene picks,
   *  Update/Reset Scene, flares, Scene Morph) — whichever of delay_ms /
   *  delay_updates comes first; delay_ms 0 waits on updates alone. */
  delay_updates: number | null;
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

export interface IntensityLane {
  id: string;
  name: string;
  labels: string[];
  threshold: number; // lower bound on the 0-1 intensity scale; lanes[0] = default (ignored)
  /** Light Mode Chooser lanes only (source 'display_mode'): the resolved
   *  Dark/Light mode that selects this lane. */
  mode?: 'dark' | 'light' | null;
  scope: MorphScope | null; // per-lane Target
  actions: Action[];
}

export interface IntensityChooserAction extends ActionBase {
  type: 'intensity_chooser';
  id: string;
  /** Ramp override: forced on every descendant action of the chosen lane
   *  (through event_refs / scene groups / scene lanes); ⚡/🎲-bindable.
   *  null = parent (nearest ancestor override, else each action's own ramp).
   *  Deeper overrides (scene group / scene ramp) win over this one. */
  ramp_ms?: Bindable<number> | null;
  /** 'display_mode' = the Light Mode Chooser face: the resolved Dark/Light
   *  mode (TopBar → trigger → scene group → scene) picks the lane, re-resolved
   *  at fire time. */
  source: 'trigger_intensity' | 'display_mode';
  /** display_mode source only: lane mode used when the cascade resolves "default". */
  default_mode?: 'dark' | 'light';
  scope: MorphScope | null; // default Target for lanes
  lanes: IntensityLane[];
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
  | SceneMorphAction
  | DeviceSettingsAction
  | BrightnessAction
  | RandomGroupAction
  | SequenceGroupAction
  | ParallelGroupAction
  | IntensityChooserAction;

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
  | 'charge' | 'lull' | 'drop'
  | 'scene_group'
  | 'device_settings' | 'composite';

/** One member of a scene_group event (weight matters in weighted mode). */
export interface SceneGroupMember {
  event_id: string;
  weight: number;
}

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

  /** scene_update / scene_group only: ramp override forced on every action
   *  this scene fire runs; ⚡/🎲-bindable. null = parent (inherit the nearest
   *  ancestor override, e.g. an Intensity Scene chooser's). The deepest
   *  override wins: scene > scene group > chooser. */
  ramp_ms?: Bindable<number> | null;

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

  /** event_type "scene_group": member Scene Updates + selection behavior
   *  (cursor lives in the engine and persists across songs). */
  scene_group_members: SceneGroupMember[];
  scene_group_mode: 'cycle' | 'weighted';
  scene_group_cycle_behavior: 'wrap' | 'bounce';
  scene_group_exclude_current: boolean;
  /** Cycle mode: a fresh call (group wasn't active) starts at a random member. */
  scene_group_random_start: boolean;
  /** Color Group (ColorSetCard kind="group") this scene group designates —
   *  Set Color actions set to "Scene Group" pull from it. '' = none. */
  scene_group_color_ref_id: string;
  /** Dark/Light variants of the designated Color Group: used instead of the
   *  base ref while the resolved display mode is dark/light. '' = no variant. */
  scene_group_dark_color_ref_id: string;
  scene_group_light_color_ref_id: string;

  /** Display-mode cascade level carried by this event: scene_group = level 3,
   *  scene_update = level 4. 'default' defers downward. */
  display_mode: DisplayMode;

  event_offset_ms: number;
}

/** Scene-family event types that render as morph lanes. scene_group is
 *  deliberately NOT here — it renders a members editor, not lanes. */
export const SCENE_EVENT_TYPES: EventType[] = [
  'scene_update', 'update_scene', 'reset_scene',
  'shape_flare', 'color_flare', 'combo_flare',
  'charge', 'lull', 'drop',
];

/** A scene_update's pinned lanes, by index. Charge/Lull/Drop carry the
 *  per-scene extras fired alongside the LedFX phase choreography. */
export const SCENE_LANE_NAMES = [
  'First', 'Rest', 'Shape', 'Color', 'Charge', 'Lull', 'Drop',
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
  charge: 'Charge',
  lull: 'Lull',
  drop: 'Drop',
  scene_group: 'Scene Group',
  device_settings: 'Device Settings',
  composite: 'Composite',
};
