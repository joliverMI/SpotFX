/** TS mirrors for models/scene_v2.py (SPECTRA SceneV2). */

export interface SceneColorAssignment {
  /** "set" = colors come from the active Color Set at fire time;
   *  "fixed" = the scene pins its own colors. */
  mode: 'set' | 'fixed';
  color_kind: 'gradient' | 'solid' | null;
  color_value: string | null;
  bg_color: string | null;
  bg_mode: 'additive' | 'overwrite' | null;
}

export interface SceneDeviceConfig {
  id: string;
  /** "all" targets every imported virtual (target stays empty);
   *  overrides layer all < category < virtual. */
  target_kind: 'all' | 'category' | 'virtual';
  target: string;
  effect_type: string;
  params: Record<string, number | boolean | string>;
  color: SceneColorAssignment;
  brightness: number | null;
  background_brightness: number | null;
}

export interface FlareBand {
  intensity_min: number;
  intensity_max: number;
  curve: 'linear' | 'ease_in' | 'ease_out' | 'pulse';
  gain: number;
  param_patch: Record<string, number>;
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
  flare_bands: FlareBand[];
  choreography: PhaseChoreography;
  accept_all_sets: boolean;
  accepted_set_ids: string[];
}

/** Computed wheel identity of a Color Set (design answer 2). position_deg is
 * null for rainbow sets (span > 180°) and for achromatic sets. */
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

export interface FireResult {
  dry_run: boolean;
  writes: CompiledWrite[];
}

/** Per-param metadata from /effect-params/config `effects` section. */
export interface EffectParamMeta {
  label?: string;
  type?: 'numeric' | 'toggle' | string;
  min?: number;
  max?: number;
  /** The effect's real default, baked from the fx schemas
   *  (scripts/backfill_param_defaults.py) — what an enabled param starts at. */
  default?: number | boolean;
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
});

export const emptyBand = (): FlareBand => ({
  intensity_min: 0,
  intensity_max: 1,
  curve: 'linear',
  gain: 1,
  param_patch: {},
});

export function newScene(id: string): SceneV2 {
  return {
    id,
    name: 'New Scene',
    labels: [],
    devices: [],
    flare_bands: [],
    choreography: { enabled: false, transition_ms: 800, transition_mode: 'Add', anchor_frac: 0.45 },
    accept_all_sets: true,
    accepted_set_ids: [],
  };
}
