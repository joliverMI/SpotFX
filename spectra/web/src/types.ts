/** TS mirrors for spectra/models — the grown scene model. */
import { uuid } from './lib/uid';

export type SignalName =
  | 'rms_total' | 'rms_bass' | 'onset_score'
  | 'section_energy' | 'trigger_intensity' | 'random';

export interface BindingStep {
  threshold: number;
  value: number | boolean | string;
}

export interface ValueBinding {
  bind: 'signal';
  signal: SignalName;
  window_beats: number;
  window_dir: 'past' | 'future' | 'centered';
  mode: 'map' | 'steps';
  in_min: number;
  in_max: number;
  out_min: number;
  out_max: number;
  steps: BindingStep[];
  fallback: number | boolean | string | null;
  random_sign: boolean;
  /** 🎲 correlation: bindings sharing a letter share one roll per fire. */
  dice: string | null;
}

export type ParamScalar = number | boolean | string;
export type ParamValue = ParamScalar | ValueBinding;

export const isBinding = (v: unknown): v is ValueBinding =>
  typeof v === 'object' && v !== null && (v as ValueBinding).bind === 'signal';

export interface SceneColorAssignment {
  mode: 'set' | 'fixed';
  color_kind: 'gradient' | 'solid' | null;
  color_value: string | null;
  bg_color: string | null;
  bg_mode: 'additive' | 'overwrite' | null;
}

export interface CurveMapPoint { x: number; y: number; }

export interface DriftSpec {
  kind: 'creep' | 'follow';
  rate_per_min: number;
  lo: number;
  hi: number;
  motion: 'bounce' | 'wrap' | 'hold';
  curve_ref: string | null;
  inline_points: CurveMapPoint[] | null;
  slew_s: number;
}

export interface DriftRef {
  profile: string | null;
  inline: DriftSpec | null;
}

/** One rung of an entry's intensity-conditional effect selection: at/above
 * threshold the entry resolves to THIS effect with THIS param set. Every
 * variant (base + steps) must name a distinct effect. */
export interface EffectStep {
  threshold: number;
  effect_type: string;
  params: Record<string, ParamValue>;
}

export interface SceneDeviceConfig {
  id: string;
  target_kind: 'all' | 'category' | 'virtual';
  target: string;
  effect_type: string;
  params: Record<string, ParamValue>;
  /** [] = the single-effect form (the plain default). Base effect_type/
   * params is the entry below the first threshold; the last step whose
   * threshold <= fire intensity wins, replacing effect AND params. */
  effect_steps: EffectStep[];
  color: SceneColorAssignment;
  brightness: number | ValueBinding | null;
  background_brightness: number | ValueBinding | null;
  drift: Record<string, DriftRef>;
}

/** A NAMED flare kind (item-8 shape): drift_jump jumps the drift (colour
 * set via the shipped selector, or a 🎲 re-roll); momentary spikes and
 * RETURNS; permanent lands and BECOMES the baseline drift carries from. */
export interface FlareKind {
  name: string;
  type: 'drift_jump' | 'momentary' | 'permanent';
  jump: 'color_set' | 'dice' | null;
  params: Record<string, number>;
  gain: number;
}

export interface FlareBand {
  intensity_min: number;
  intensity_max: number;
  /** Legacy fields — auto-named into kinds on load; always neutral after. */
  curve: 'linear' | 'ease_in' | 'ease_out' | 'pulse';
  gain: number;
  param_patch: Record<string, number>;
  /** kind name → scale factor: the band SELECTS AND SCALES the kinds. */
  kinds: Record<string, number>;
}

export interface ResponseSpec {
  bands: FlareBand[];
  /** Legacy per-class flags — auto-named into drift-jump kinds on load. */
  reroll_dice: boolean;
  color_set_jump: boolean;
}

export type ResponseClass = 'flare' | 'charge' | 'lull' | 'drop';
export const RESPONSE_CLASSES: ResponseClass[] = ['flare', 'charge', 'lull', 'drop'];

export interface ColorJourneySpec { degrees_per_min: number; }

export interface SceneColorJourney {
  mode: 'inherit' | 'override';
  pace_factor: number;
  journey: ColorJourneySpec | null;
}

export interface PhaseChoreography {
  enabled: boolean;
  transition_ms: number;
  transition_mode: string;
  anchor_frac: number;
}

/** OVERRIDE BLEND equivalent, charge/lull facet — null = the fixed class
 * default (charge 4000 ms, lull 2500 ms); drop is never overridable. */
export interface PhaseBlend {
  charge_ramp_ms: number | null;
  lull_ramp_ms: number | null;
}

export interface SceneV2 {
  id: string;
  name: string;
  labels: string[];
  devices: SceneDeviceConfig[];
  flare_kinds: FlareKind[];
  responses: Partial<Record<ResponseClass, ResponseSpec>>;
  color_journey: SceneColorJourney;
  choreography: PhaseChoreography;
  phase_blend: PhaseBlend;
  /** OVERRIDE BLEND equivalent, scene-entry facet: blend this scene's
   * writes in over this ramp (ms) instead of an instant jump when it
   * fires live. 0 = today's unchanged instant-jump behaviour. */
  entry_ramp_ms: number;
  accept_all_sets: boolean;
  accepted_set_ids: string[];
}

export interface ColorWheelPosition {
  set_id: string;
  position_deg: number | null;
  rainbow: boolean;
  span_deg: number;
  resultant: number;
}

export interface CompiledWrite {
  virtual_id: string;
  effect_type: string;
  config: Record<string, unknown>;
}

export interface ResolvedBinding {
  entry: string;
  param: string;
  signal: SignalName;
  dice: string | null;
  value: unknown;
}

export interface FireResult {
  dry_run: boolean;
  intensity: number;
  writes: CompiledWrite[];
  resolved_bindings: ResolvedBinding[];
  dice_rolls: Record<string, number>;
}

/** Per-param metadata from /spectra/api/registry `effects` section. */
export interface EffectParamMeta {
  label?: string;
  type?: 'numeric' | 'integer' | 'toggle' | 'enum' | 'string' | string;
  min?: number;
  max?: number;
  aspect?: string;
  options?: string[];
  options_source?: string;
  default?: number | boolean | string;
}

export interface Registry {
  categories: Record<
    string,
    { id: string; parent_id: string | null; virtuals: string[]; effects: string[] }
  >;
  effects: Record<string, { params?: Record<string, EffectParamMeta> }>;
}

export interface DriftProfile {
  id: string;
  name: string;
  spec: DriftSpec;
}

export interface RoomColorState {
  journey: ColorJourneySpec;
  wheel_position_deg: number | null;
  active_set_id: string | null;
}

/** Room-control surface (spectra-kept-equivalents): the legacy Brightness
 * Multiplier / ledfx_ambient / ledfx_ambient_color / ledfx_global_transition
 * action equivalents. brightness_multiplier is the only one wired to a
 * write seam today (fx_executor + scene_compiler); ambient_enabled/_color
 * and global_transition_ms are state-only until the room-modes build. */
export interface RoomControlState {
  brightness_multiplier: number;
  ambient_enabled: boolean;
  ambient_color: string | null;
  global_transition_ms: number;
}

/** Full spot-effects Colour Set card shape (read + the one supported
 * opt-out toggle through the spot-effects API — never modified otherwise). */
export interface SpotColorSetCard {
  id: string;
  name: string;
  kind: 'set' | 'group';
  scene_v2_opt_out?: boolean;
  [key: string]: unknown;
}

export const emptyColor = (): SceneColorAssignment => ({
  mode: 'set',
  color_kind: null,
  color_value: null,
  bg_color: null,
  bg_mode: null,
});

export const emptyDevice = (id: string): SceneDeviceConfig => ({
  id,
  target_kind: 'category',
  target: '',
  effect_type: '',
  params: {},
  effect_steps: [],
  color: emptyColor(),
  brightness: null,
  background_brightness: null,
  drift: {},
});

export const emptyBand = (min = 0, max = 1): FlareBand => ({
  intensity_min: min,
  intensity_max: max,
  curve: 'linear',
  gain: 1,
  param_patch: {},
  kinds: {},
});

export const emptyResponse = (): ResponseSpec => ({
  bands: [],
  reroll_dice: false,
  color_set_jump: false,
});

export function newScene(id: string): SceneV2 {
  return {
    id,
    name: 'New Scene',
    labels: [],
    devices: [],
    flare_kinds: [],
    responses: {},
    color_journey: { mode: 'inherit', pace_factor: 1, journey: null },
    choreography: { enabled: false, transition_ms: 800, transition_mode: 'Add', anchor_frac: 0.45 },
    phase_blend: { charge_ramp_ms: null, lull_ramp_ms: null },
    entry_ramp_ms: 0,
    accept_all_sets: true,
    accepted_set_ids: [],
  };
}

export function sceneDiceLetters(scene: SceneV2): string[] {
  const letters = new Set<string>();
  for (const dev of scene.devices) {
    const values = [...Object.values(dev.params), dev.brightness, dev.background_brightness];
    for (const step of dev.effect_steps ?? []) values.push(...Object.values(step.params));
    for (const v of values) {
      if (isBinding(v) && v.dice) letters.add(v.dice);
    }
  }
  return [...letters].sort();
}

/* ── S2 evolution-engine status (GET /api/engine/status) ── */

export interface DriftMechanismStatus {
  virtual_id: string;
  param: string;
  kind: 'creep' | 'follow';
  position?: number;
  lo?: number;
  hi?: number;
  rate_per_min?: number;
  motion?: string;
  slew_s?: number;
}

export interface JourneyDestination {
  set_id: string;
  set_name: string;
  position_deg: number;
  pace_deg_per_min: number;
  progress: number;         // 0..1 of the walk completed
  rung: string;             // selector rung that picked it
}

export interface DriftLegRecord {
  virtual_id: string;
  param: string;
  kind: string;
  target: number;
  duration_ms: number;
}

export interface SurgeRecord {
  at: number;
  class: string;
  intensity: number;
  result: string;
  band?: { intensity_min: number; intensity_max: number };
  kinds?: { name: string; type: string; scale: number; jump?: string }[];
  color_jump?: { result: string; picked_id?: string; rung?: string };
}

export interface EngineStatus {
  increment: string;
  dark: boolean;
  executor: {
    mode: string;
    recent_writes: {
      seq: number; at: number; kind: string; virtual_id: string;
      effect_type: string; params: Record<string, unknown>; duration_ms: number;
    }[];
  };
  conductor: {
    executor_mode: string;
    leg_s: number;
    active_scene: { id: string; name: string } | null;
    deferred_by: string | null;
    journey: {
      custody: string;
      degrees_per_min: number;
      room_degrees_per_min: number;
      wheel_position_deg: number | null;
      active_set_id: string | null;
      rainbow_paused: boolean;
      destination: JourneyDestination | null;
    };
    mechanisms: DriftMechanismStatus[];
    last_leg: {
      at: number; intensity: number;
      journey: Record<string, unknown>;
      legs: DriftLegRecord[];
    } | null;
    last_rebaseline: {
      at: number; scene_id: string; scene_name: string; mechanisms: number;
      journey_custody: string; journey_degrees_per_min: number;
    } | null;
  };
  responses: { recent_surges: SurgeRecord[] };
  bridge: {
    connected: boolean;
    ws_url: string;
    last_message_age_s: number | null;
    track: {
      uri: string | null; title: string | null;
      is_playing: boolean | null; position_ms: number | null;
    } | null;
    deferral: string | null;
    intensity: number | null;
    genre_bucket: string | null;
    last_event: {
      at: number; event_type: string; event_name: string;
      class: string | null; intensity: number | null;
    } | null;
    counts: Record<string, number>;
  };
}

/** TS mirrors for spectra/models/trigger.py — THE KEYSTONE: a per-song
 * moment that fires one SPECTRA-native action. Discriminated by `kind`,
 * same convention as pydantic's Field(discriminator="kind"). */
export interface FireSceneAction {
  kind: 'fire_scene';
  scene_id: string;
  intensity: number;
  color_set_id: string | null;
}

export interface FireResponseAction {
  kind: 'fire_response';
  event_class: ResponseClass;
  intensity: number;
}

export interface SelectColorSetAction {
  kind: 'select_color_set';
  set_id: string;
}

export type TriggerAction = FireSceneAction | FireResponseAction | SelectColorSetAction;
export type TriggerActionKind = TriggerAction['kind'];

export interface SpectraTrigger {
  id: string;
  timestamp_ms: number;
  enabled: boolean;
  action: TriggerAction;
}

export const newTrigger = (timestampMs: number): SpectraTrigger => ({
  id: uuid(),
  timestamp_ms: Math.max(0, Math.round(timestampMs)),
  enabled: true,
  action: { kind: 'fire_scene', scene_id: '', intensity: 0.5, color_set_id: null },
});
