/** TS mirrors for spectra/models — the grown scene model. */

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
  motion: 'bounce' | 'wrap';
  curve_ref: string | null;
  inline_points: CurveMapPoint[] | null;
  slew_s: number;
}

export interface DriftRef {
  profile: string | null;
  inline: DriftSpec | null;
}

export interface SceneDeviceConfig {
  id: string;
  target_kind: 'all' | 'category' | 'virtual';
  target: string;
  effect_type: string;
  params: Record<string, ParamValue>;
  color: SceneColorAssignment;
  brightness: number | ValueBinding | null;
  background_brightness: number | ValueBinding | null;
  drift: Record<string, DriftRef>;
}

export interface FlareBand {
  intensity_min: number;
  intensity_max: number;
  curve: 'linear' | 'ease_in' | 'ease_out' | 'pulse';
  gain: number;
  param_patch: Record<string, number>;
}

export interface ResponseSpec {
  bands: FlareBand[];
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

export interface SceneV2 {
  id: string;
  name: string;
  labels: string[];
  devices: SceneDeviceConfig[];
  responses: Partial<Record<ResponseClass, ResponseSpec>>;
  color_journey: SceneColorJourney;
  choreography: PhaseChoreography;
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
});

export const emptyResponse = (): ResponseSpec => ({
  bands: [],
  reroll_dice: true,
  color_set_jump: false,
});

export function newScene(id: string): SceneV2 {
  return {
    id,
    name: 'New Scene',
    labels: [],
    devices: [],
    responses: {},
    color_journey: { mode: 'inherit', pace_factor: 1, journey: null },
    choreography: { enabled: false, transition_ms: 800, transition_mode: 'Add', anchor_frac: 0.45 },
    accept_all_sets: true,
    accepted_set_ids: [],
  };
}

export function sceneDiceLetters(scene: SceneV2): string[] {
  const letters = new Set<string>();
  for (const dev of scene.devices) {
    for (const v of [...Object.values(dev.params), dev.brightness, dev.background_brightness]) {
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
  band?: { intensity_min: number; intensity_max: number; curve: string; gain: number };
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
