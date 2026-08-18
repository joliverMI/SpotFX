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

/** One param's target expression on a momentary/permanent kind — the
 * owner's five-ways extension. absolute (default, legacy-compatible) is
 * value verbatim; offset is a signed delta from the CARRIED BASELINE at
 * fire time (up = positive, down = negative — a creep's current wander
 * position, not its static declared baseline); random rolls once per kind
 * execution in [lo, hi] and broadcasts like an absolute value. The other
 * two ways aren't modes here: INTENSITY-DRIVEN is the band's own ×scale
 * (composes with every mode), ABSOLUTE is this type's default. */
export interface ParamTarget {
  mode: 'absolute' | 'offset' | 'random';
  value: number | null;
  offset: number | null;
  lo: number | null;
  hi: number | null;
}

/** A NAMED flare kind (item-8 shape): drift_jump jumps the drift (colour
 * set via the shipped selector, or a 🎲 re-roll); momentary spikes and
 * RETURNS; permanent lands and BECOMES the baseline drift carries from.
 * hold_ms (momentary only; null = the fixed PULSE_HOLD_S default, 250 ms)
 * is the CHOSEN HOLD before the release glide starts. */
export interface FlareKind {
  name: string;
  type: 'drift_jump' | 'momentary' | 'permanent';
  jump: 'color_set' | 'dice' | null;
  params: Record<string, ParamTarget>;
  gain: number;
  hold_ms: number | null;
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
  /** UPDATE (RULING.md 2026-08-14): names a type="permanent" entry in
   * flare_kinds as this scene's own UPDATE content — a fire_scene_update
   * trigger fires it directly, bypassing band selection. null = not
   * authored yet, a fire_scene_update trigger on this scene is a no-op. */
  update_kind: string | null;
  color_journey: SceneColorJourney;
  choreography: PhaseChoreography;
  phase_blend: PhaseBlend;
  /** OVERRIDE BLEND equivalent, scene-entry facet: blend this scene's
   * writes in over this ramp (ms) instead of an instant jump when it
   * fires live. 0 = today's unchanged instant-jump behaviour. */
  entry_ramp_ms: number;
  accept_all_sets: boolean;
  accepted_set_ids: string[];
  /** Per-scene mode availability (owner ask 2026-08-17) — see
   * ModeAvailabilityToggle.tsx. "light": skipped by automatic selection
   * while the room is dark. "dark": skipped while the room is light.
   * "default": always available. */
  display_availability: DisplayAvailability;
  /** Per-scene colour-set PREFERENCE (owner ask 2026-08-17) — a SECOND
   * axis from display_availability above, not the same control: that field
   * decides whether THIS SCENE plays at all in the current room mode; this
   * one decides WHICH COLOUR SETS it draws from once it does play. See
   * ColorSetPreferenceToggle.tsx. "default" = no preference (unchanged
   * behaviour). "dark"/"light" narrow the automatic colour-set roll to
   * sets marked the same way (plus every unmarked set — a preference never
   * excludes a set nobody has classified yet) UNLESS the room's own
   * display_mode is explicitly set to the opposite mode, which always
   * wins over the scene's preference. */
  preferred_color_set_mode: DisplayAvailability;
}

export type DisplayAvailability = 'default' | 'dark' | 'light';

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
 * action equivalents. brightness_multiplier is wired at a write seam
 * (fx_executor + scene_compiler); ambient_mode/_color drives a live
 * Hue takeover (spectra/services/ambient.py via ambient_music_gate.py)
 * reconciled on every PUT that changes them; global_transition_ms is
 * state-only.
 * scene_change_mode is the Admiral's settings model (three additive tiers,
 * replacing front 3's plain midsong_triggers_enabled bool): "transitions" =
 * a scene change on every song transition only; "analysed" = transitions +
 * GENERATED (seeded) mid-song triggers; "full" = transitions + generated +
 * hand-authored triggers + response-engine flares. Default "full". */
export type SceneChangeMode = 'transitions' | 'analysed' | 'full';

/** Ambient's own three settings, in the Admiral's own language
 * (spectra/services/ambient_music_gate.py) — "off" never holds; "always"
 * holds Hue lit at ambient_color unconditionally while every other device
 * keeps running the show; "auto" holds only while nothing is playing and
 * releases the instant music starts, returning on its own when it stops. */
export type AmbientMode = 'off' | 'always' | 'auto';

/** Legacy's Default/Dark/Light display-mode cycle, all three states
 * (spectra/services/dark_light.py). "default" is his word "hybrid" — defer
 * to whatever the scene authors; labelled "Hybrid" in the UI, kept
 * "default" internally per his standing ruling. Migration note (load
 * bearing): the old dark_mode_enabled bool mapped true->"dark",
 * false->"default" — NEVER "light" — see room_controls.py's module
 * docstring for why. */
export type DisplayMode = 'default' | 'dark' | 'light';

export interface RoomControlState {
  /** Legacy global Default/Dark/Light display-mode toggle equivalent
   * (services/display_mode.py + LedFX's dark_lock — see spectra/services/
   * dark_light.py's docstring for the full fidelity mapping). */
  display_mode: DisplayMode;
  /** Legacy's configurable forced Light background
   * (settings.display_light_bg_color/_brightness), ported verbatim
   * (default #201830 @ 0.3) — the colour/brightness "light" forces onto
   * every non-shielded virtual's background, unconditionally. */
  display_light_bg_color: string;
  display_light_bg_brightness: number;
  /** Applies to BOTH "dark" and "light" — a shielded device keeps its own
   * authored background in either forced mode. */
  dark_light_shield_categories: string[];
  dark_light_shield_virtuals: string[];
  brightness_multiplier: number;
  ambient_mode: AmbientMode;
  ambient_color: string | null;
  /** The SECOND ambient colour, held while dark mode is on (his ruling:
   * "one color for regular ambient light mode or hybrid mode and then one
   * color for dark mode"). `null` means "not customized yet" — it defers
   * to ambient_color (spectra/services/room_controls.py's
   * effective_ambient_color), so the two stay identical by construction
   * ("for now make them the same") until he picks a distinct dark colour
   * with the same colour picker. Switching display_mode into/out of "dark"
   * while Ambient is holding re-applies live at whichever colour is now in
   * effect, eased through Ambient's own existing glide (same mechanism a
   * plain colour edit already uses) — never a snap. */
  ambient_color_dark: string | null;
  /** WHICH Hue entertainment areas Ambient reaches (spectra/services/
   * ambient.py, "Hue entertainment-area selection" — ported from legacy's
   * own per-group picker on the front-page Ambient button). `[]` (the
   * default) means every live Hue device — today's unmodified behaviour.
   * A non-empty list is the exact device ids (see AmbientHueGroup) Ambient
   * may hold; any other live Hue device is left running its normal show,
   * never frozen. */
  ambient_hue_group_ids: string[];
  global_transition_ms: number;
  scene_change_mode: SceneChangeMode;
  /** Legacy Now Playing "Force Scene" control, ported verbatim: while
   * enabled, every scene the system would otherwise pick automatically
   * (sequencer roll, trigger fire, or the automatic transition fire) fires
   * force_scene_scene_id instead. Does not affect manual editor test-fires. */
  force_scene_enabled: boolean;
  force_scene_scene_id: string | null;
}

/** What actually happened to the room's virtuals on the last display-mode
 * change — present on PUT /room-controls's response only when the mode (or,
 * while dark/light, a shield-list edit; or, while light, a bg colour/
 * brightness edit) actually changed (spectra/api/room_controls.py).
 * "default"/"dark"/"light" is a real live push, named honestly — "default"
 * is the ACTUAL nothing-forced state (his word "hybrid"; before this
 * three-state rebuild the off-state was mislabelled "light" while behaving
 * as this). "no-devices" means the switch saved but SPECTRA doesn't know of
 * any virtual to touch; "handover-in-progress"/"released" mean the light
 * ownership record refused a write right now; "failed" means an unexpected
 * error reaching LedFX. `locked` is the CONFIRMED (read back from LedFX,
 * not merely posted) set of virtuals actually holding dark_lock=true;
 * `lit` (light only) is the confirmed set whose background actually landed
 * at the configured light colour/brightness; `unconfirmed` names any
 * virtual whose read-back state didn't match what was requested (dark_lock
 * OR the light background). `restored` (default only) lists virtuals
 * repainted from the pre-dark snapshot — empty when there was nothing to
 * restore OR when `repaint_skipped: "music_playing"` is present: music was
 * actively playing, so the stale pre-dark snapshot was deliberately NOT
 * forced back (dark_lock still cleared) — the room's own live show repaints
 * it on its next natural fire instead of a frozen look overriding it. */
export interface DarkLightResult {
  status: 'default' | 'dark' | 'light' | 'no-devices' | 'handover-in-progress' | 'released' | 'failed';
  locked?: string[];
  shielded?: string[];
  restored?: string[];
  lit?: string[];
  repaint_skipped?: 'music_playing';
  unconfirmed?: string[];
  error?: string;
}

/** What actually happened to the room's Hue devices on the last ambient
 * change — present on PUT /room-controls's response only when the ambient
 * fields changed (spectra/api/room_controls.py). "on"/"off" is a real live
 * takeover; "dark"/"no-hue-devices" means the switch saved but nothing was
 * touched (SPECTRA doesn't own the room right now, or there's no Hue
 * device in it); "failed" means SPECTRA tried and every live Hue device
 * rejected it (bridge unreachable, etc.); "partial" means at least one
 * device held, but SPECTRA read every light back from the bridge and one
 * or more did NOT confirm the colour after bounded, spaced retries — named
 * in `unconfirmed` by his own bulb name (spectra/services/ambient.py's
 * read-back confirmation) — the room bar surfaces all of these so the
 * control never silently lies about having done something. `lights_set` is
 * a CONFIRMED count (read back from the bridge), not merely attempted;
 * `lights_total` is how many lights were targeted. */
export interface AmbientResult {
  status: 'on' | 'off' | 'dark' | 'no-hue-devices' | 'failed' | 'partial' | 'yielding';
  devices?: string[];
  lights_set?: number;
  lights_total?: number;
  unconfirmed?: string[];
  /** Devices released in the SAME call — present when a Hue area fell out
   * of ambient_hue_group_ids while Ambient stayed engaged (the group he
   * just deselected), not on a plain hold or a whole-room OFF. */
  released?: string[];
}

/** spectra/services/ambient_music_gate.py's status() — the room's honest,
 * always-live read of what Ambient is ACTUALLY doing, distinct from
 * AmbientResult above (a one-shot save outcome). `setting` is the chosen
 * AmbientMode (what the control says); `mode` is the LIVE reality: "off"
 * (setting is off), "holding" (every claimed light CONFIRMED lit at
 * ambient_color right now — true throughout "always", and only while
 * confirmed-quiet under "auto"), "partial" (Ambient believes it should be
 * holding but the last check — write or periodic — found at least one
 * light not actually lit, or found nothing left to hold at all), "yielding"
 * (setting isn't off, but standing aside for music or an unresolved
 * playback read — only reachable under "auto"), "transitioning" (a
 * hold/release is physically in flight). `held` is gated on that same
 * confirmation, not a bare write-intent flag — it can never read true for
 * a light that's actually off (fixed 2026-08-15 after his room sat
 * reporting `held: true` all night while every bulb was off). `verify` is
 * the confirmation itself (write read-back or the independent periodic
 * GET-only recheck — spectra/services/ambient.py's verify_held(), which
 * never writes); `verified_age_s` is how many seconds old it is — present
 * whenever there's a confirmation to age, so a caller can always tell
 * "confirmed 4s ago" from "confirmed 20 minutes ago" instead of treating
 * every value as equally live. Folded into EngineStatus so the existing 3s
 * poll shows it live with no separate request. */
export interface AmbientVerify {
  status: 'verified' | 'dark' | 'no-hue-devices';
  lights_lit?: number;
  lights_total?: number;
  unlit?: string[];
}

export interface AmbientGateStatus {
  setting: AmbientMode;
  mode: 'off' | 'holding' | 'partial' | 'yielding' | 'transitioning';
  held: boolean;
  /** The RESOLVED device ids currently held — [] when not held, or when
   * the selection is "every live Hue device" (ambient_hue_group_ids: []),
   * the default — see spectra/services/ambient_music_gate.py's status(). */
  groups: string[];
  result?: AmbientResult;
  verify?: AmbientVerify;
  verified_age_s?: number;
}

/** One entry from GET /api/room-controls/ambient-groups — a live Hue
 * entertainment area ambient_hue_group_ids can name (spectra/services/
 * ambient.py's list_groups(), the analogue of legacy's own
 * resolve_groups()). `id` is the same device id RoomControlState.
 * ambient_hue_group_ids and AmbientGateStatus.groups use. */
export interface AmbientHueGroup {
  id: string;
  name: string;
}

/** What happened to Force Scene's pin on the last room-controls save
 * (spectra/services/room_controls.py's reconcile_force_scene_if_changed) —
 * present on PUT /room-controls's response only when the edit was a pin
 * change (enabling it, or repinning a different scene while already
 * enabled). fire_scene_by_id's own redirect is passive — it only fires
 * when something else was already about to pick a scene, so on a song
 * with no triggers the pin could sit there doing nothing. This is the fix:
 * the pinned scene fires directly on the pinning edit. "fired" is a real
 * immediate activation; "skipped" means nothing was pinned yet, or the
 * pinned id doesn't resolve to a real scene — always named, never a
 * silent no-op; "error" means the fire itself raised. Re-saving an
 * unrelated field with the pin unchanged reports nothing (no key on the
 * response at all) — it wasn't a pin edit. */
export interface ForceSceneResult {
  status: 'fired' | 'skipped' | 'error';
  scene_id?: string;
  scene_name?: string;
  reason?: string;
}

export interface RoomControlsSaveResult extends RoomControlState {
  status: 'saved';
  ambient_result?: AmbientResult;
  dark_light_result?: DarkLightResult;
  force_scene_result?: ForceSceneResult;
}

/** Device-preview strip (data/spectra-device-preview-plan/report.md).
 * `favorite_virtual_ids` is his explicit choice (empty = none made yet);
 * `effective_virtual_ids` is what's actually shown — his choice, or the
 * zero-configuration default (spectra/services/device_preview.py's
 * genuinely-driven-virtual auto-population) when he hasn't picked any.
 * `is_default` tells the picker whether it's showing his own list or the
 * auto-populated one. */
export interface DevicePreviewFavorites {
  favorite_virtual_ids: string[];
  effective_virtual_ids: string[];
  is_default: boolean;
}

/** GET/POST /api/device-preview/{status,pause,resume} and the WS status
 * push — `connected` is the live upstream connection (whichever `source`
 * names), honestly false whenever paused (see services/device_preview.py's
 * module docstring for why this must never lie). `source` is
 * ownership-routed (2026-08-16 correction — the strip used to assume
 * LedFX was always the writer, which is wrong in his normal S3 operating
 * state): "facade" reads SPECTRA's own in-process render pipeline (no
 * LedFX involved at all — his normal state), "ledfx" reads the external
 * LedFX process's visualisation feed (only when spot-effects owns the
 * lights), "none" means nobody currently owns the lights (a handover in
 * flight, or released) so there is nothing to preview. */
export interface DevicePreviewStatus {
  paused: boolean;
  connected: boolean;
  favorite_virtual_ids: string[];
  target_fps: number;
  frames_relayed: number;
  source: 'facade' | 'ledfx' | 'none';
}

/** One relayed frame off /api/device-preview/ws. When `source: "ledfx"`
 * this is LedFX's own VisualisationUpdateEvent shape passed through
 * unchanged; when `source: "facade"` it's SPECTRA's own independent
 * encoding of the same real per-virtual pixel buffer (module docstring,
 * spectra/services/device_preview.py) — deliberately built to the SAME
 * wire shape so this type and decodePixels() need no source-aware branch
 * (pixels stay base64-or-list; decoded client-side either way). */
export interface DevicePreviewFrame {
  type: 'device_preview_frame';
  vis_id: string;
  pixels: string | number[][];
  shape: [number, number];
  is_device: boolean;
}

/* ── settings console (standing order 5: talk to the software) ──
 * spectra/services/settings_console.py is the authority: SettingSpec's
 * min/max/choices are read live off RoomControlState's own Field
 * constraints, so this UI is a display of declared data, never a form
 * that writes directly — only the chat (POST /settings-console/message)
 * changes anything. */
export type SettingKind = 'float' | 'int' | 'bool' | 'enum' | 'color';

export interface SettingSpec {
  key: string;
  label: string;
  kind: SettingKind;
  description: string;
  unit: string | null;
  min: number | null;
  max: number | null;
  choices: string[] | null;
}

export interface SettingValue extends SettingSpec {
  value: number | boolean | string | null;
}

export interface SettingsRegistry {
  settings: SettingValue[];
}

export type SettingChangeSource = 'agent' | 'human' | 'undo';

export interface SettingChangeEntry {
  id: string;
  ts_ms: number;
  key: string;
  old_value: unknown;
  new_value: unknown;
  source: SettingChangeSource;
  undone: boolean;
}

export interface AppliedSettingChange extends SettingChangeEntry {
  status: 'applied';
}

/** One applied change from Sonic (spectra/services/settings_agent.py) —
 * settings and scene/flare operations return different domain-specific
 * fields (a settings change carries `key`; a scene change carries
 * `scene_id`/`op` and sometimes `flare_kind`), so this is deliberately
 * loose beyond the handful every applied result shares. See
 * scene_console.py / settings_console.py for each op's exact shape. */
export interface SonicAppliedChange {
  status: 'applied';
  id: string;
  ts_ms: number;
  op?: string;
  source: SettingChangeSource;
  key?: string;
  scene_id?: string;
  scene_name?: string;
  flare_kind?: string;
  old_value?: unknown;
  new_value?: unknown;
  /** One deterministic, plain-language line built server-side from this
   * op's own structured fields — never the model's account of what it
   * did (see spectra/services/scene_console.py / settings_console.py).
   * This is what answers "did it work", not a JSON dump of this object. */
  summary?: string;
  [extra: string]: unknown;
}

/** A write op the server refused — same {status, reason, ...} shape
 * SceneOpError/SettingChangeError.payload() produce. `reason` is already
 * a plain-language sentence, exactly like `summary` is on the applied
 * side — his "if it failed, that says so just as plainly" ask. */
export interface SonicRejectedChange {
  status: 'rejected';
  reason: string;
  [extra: string]: unknown;
}

export interface SettingsMessageResult {
  session_id: string;
  reply: string;
  changes: SonicAppliedChange[];
  rejected: SonicRejectedChange[];
}

export interface UndoResult extends AppliedSettingChange {
  ambient_result?: AmbientResult;
}

export interface SettingsChatMessage {
  id: string;
  /** 'preview' renders a change's real before/after diff (SonicAppliedChange.preview,
   * read from stored data) — kept visually distinct from 'assistant' so a
   * preview is never mistaken for the model's own prose. 'status' is the
   * one-line deterministic outcome (SonicAppliedChange.summary /
   * SonicRejectedChange.reason) — always shown regardless of what the
   * model's own reply says, so the outcome is never only in its prose. */
  role: 'user' | 'assistant' | 'preview' | 'status';
  text: string;
}

/** POST /settings-console/transcribe response. vocabulary_honored is null
 * only when the request carried no vocabulary hint; otherwise the server
 * itself refuses (502) a transcription that didn't confirm true — see
 * spectra/services/transcription.py's wire-contract docstring. */
export interface TranscribeResult {
  text: string;
  vocabulary_honored: boolean | null;
}

/** One scoped FG/BG colour definition — a Set's own palette entry, or (on a
 * Group card) a field-level override layered onto whichever member gets
 * picked. Mirrors spot-effects models/color_set.py's ColorSetEntry; the
 * index signature carries fields this UI doesn't render (accent_color,
 * ramp_ms) through unmodified on save — see SpotColorSetCard's own note. */
export interface SpotColorSetEntry {
  scope: { virtual_ids: string[]; categories: string[]; roles: string[] };
  color_kind: 'gradient' | 'solid' | null;
  color_value: string | null;
  bg_color: string | null;
  bg_mode: 'additive' | 'overwrite' | null;
  brightness: number | null;
  background_brightness: number | null;
  [key: string]: unknown;
}

/** One reference to a Colour Set within a Group, with a selection weight
 * (weighted mode only). */
export interface SpotGroupMember {
  color_set_id: string;
  weight: number;
}

/** Full spot-effects Colour Set card shape — a Set (a named palette) or a
 * Group (a rotating/synced pool of Sets — day-one bar item §10). Read AND
 * authored (create/edit/delete, both kinds) through the spot-effects API
 * directly (useSaveColorSet / useDeleteColorSet) — SPECTRA's own backend
 * only ever reads this storage (spectra/services/color_sets.py), never
 * writes it, so this type round-trips whatever it received via its index
 * signature: fields this UI doesn't render (dark_variant/light_variant
 * mode lanes — owner-retired, §36 — and display_mode) are preserved
 * unmodified on save rather than silently dropped. */
export interface SpotColorSetCard {
  id: string;
  name: string;
  color?: string;
  kind: 'set' | 'group';
  labels?: string[];
  entries?: SpotColorSetEntry[];
  scene_v2_opt_out?: boolean;
  // kind === 'group' only:
  members?: SpotGroupMember[];
  mode?: 'cycle' | 'weighted';
  cycle_behavior?: 'wrap' | 'bounce';
  exclude_current?: boolean;
  palette_sync?: boolean;
  /** Per-item mode availability (owner ask 2026-08-17) — see
   * ModeAvailabilityToggle.tsx. Applies to both Sets and Groups (same
   * card, kind differentiates) — distinct from the retired display_mode
   * mode-lane field this card also round-trips unmodified. */
  display_availability?: DisplayAvailability;
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
    update_kind: null,
    color_journey: { mode: 'inherit', pace_factor: 1, journey: null },
    choreography: { enabled: false, transition_ms: 800, transition_mode: 'Add', anchor_frac: 0.45 },
    phase_blend: { charge_ramp_ms: null, lull_ramp_ms: null },
    entry_ramp_ms: 0,
    accept_all_sets: true,
    accepted_set_ids: [],
    display_availability: 'default',
    preferred_color_set_mode: 'default',
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
  ambient: AmbientGateStatus;
}

/** TS mirrors for spectra/models/trigger.py — THE KEYSTONE: a per-song
 * moment that fires one SPECTRA-native action. Discriminated by `kind`,
 * same convention as pydantic's Field(discriminator="kind"). scene_id null
 * (front 3) means "pick at fire time through the sequencer selection
 * kernel" — a generated trigger's own default; a hand-picked scene names
 * it directly. */
export interface FireSceneAction {
  kind: 'fire_scene';
  scene_id: string | null;
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

/** UPDATE (data/spectra-trigger-migration-scoping RULING.md, 2026-08-14):
 * "a major change within the scene, bigger than a flare, overriding the
 * drift, going somewhere new on a ramp-in transition." Fires the ACTIVE
 * scene's own SceneV2.update_kind by name, bypassing intensity-band
 * selection entirely (unlike fire_response) — no update_kind authored on
 * the active scene is a silent no-op. Reset is the same action. */
export interface FireSceneUpdateAction {
  kind: 'fire_scene_update';
  intensity: number;
}

export type TriggerAction = FireSceneAction | FireResponseAction | SelectColorSetAction
  | FireSceneUpdateAction;
export type TriggerActionKind = TriggerAction['kind'];

/** source/generator_key: front 3's provenance — "generated" is a
 * midsong_generator seed (generator_key ties it back to the analysis
 * moment); "authored" is everything else, including a generated trigger a
 * human has since touched (the editing API always stamps it back to
 * authored — see spectra/api/triggers.py). */
export type TriggerSource = 'authored' | 'generated';

export interface SpectraTrigger {
  id: string;
  timestamp_ms: number;
  enabled: boolean;
  source: TriggerSource;
  generator_key: string | null;
  action: TriggerAction;
}

export const newTrigger = (timestampMs: number): SpectraTrigger => ({
  id: uuid(),
  timestamp_ms: Math.max(0, Math.round(timestampMs)),
  enabled: true,
  source: 'authored',
  generator_key: null,
  action: { kind: 'fire_scene', scene_id: '', intensity: 0.5, color_set_id: null },
});

/** Feedback-session mark-then-nudge queue (Stage 2, GET /api/feedback/mark,
 * POST /api/feedback/batch). The queue itself lives client-side
 * (localStorage) until Send — see spectra/web/src/feedback/FeedbackPage.tsx. */
export interface FeedbackCapture {
  wall_ms: number;
  uri: string | null;
  position_ms: number | null;
}

export interface FeedbackEntry {
  id: string;
  wall_ms: number;
  uri: string | null;
  /** The best-known captured anchor — the optimistic guess at Mark time,
   * then whatever the background GET /api/feedback/mark patch corrects it
   * to. Nudges never mutate this directly (see nudge_offset_ms) so that
   * correction can always land without clobbering a nudge already applied.
   * Client-only; the wire value sent on Send is position_ms + nudge_offset_ms. */
  position_ms: number;
  /** Client-only: sum of his +/-1s/+/-5s taps, applied on top of
   * position_ms. Kept separate from the anchor specifically so a slow
   * background capture correction can still land after a fast nudge —
   * see FeedbackPage.tsx's handleMark. */
  nudge_offset_ms: number;
  note: string;
  /** Client-only: true once nudged or noted — drives the nudge highlight
   * flash and is otherwise informational (it no longer gates the
   * background capture patch, which now always corrects position_ms and
   * re-applies nudge_offset_ms on top). Stripped before the entry is sent
   * to POST /api/feedback/batch. */
  touched: boolean;
}

export const newFeedbackEntry = (capture: {
  wall_ms: number; uri: string | null; position_ms: number | null;
}): FeedbackEntry => ({
  id: uuid(),
  wall_ms: capture.wall_ms,
  uri: capture.uri,
  position_ms: Math.max(0, capture.position_ms ?? 0),
  nudge_offset_ms: 0,
  note: '',
  touched: false,
});

/** Stage 3 review view (GET /api/review/sessions, GET /api/review/timeline)
 * — see spectra/services/show_reconstruction.py for the merge rule this
 * mirrors. A session is one sent feedback batch. */
export type FireHistoryBucket = 'scenes' | 'responses' | 'color_sets' | 'triggers';

export interface ReviewSession {
  session_id: string;
  received_ms: number;
  note_count: number;
  uris: string[];
}

export interface ReviewEventItem {
  type: 'event';
  wall_ms: number | null;
  position_ms: number | null;
  bucket: FireHistoryBucket;
  key: string;
  detail: Record<string, unknown>;
}

export interface ReviewNoteItem {
  type: 'note';
  wall_ms: number | null;
  position_ms: number | null;
  id: string;
  note: string;
}

export type ReviewTimelineItem = ReviewEventItem | ReviewNoteItem;

export interface ReviewTimeline {
  session_id: string;
  uri: string;
  window: { start_wall_ms: number; end_wall_ms: number } | null;
  timeline: ReviewTimelineItem[];
}

/** GET/PUT/DELETE /api/intensity-scale/mark?uri= — the 2026-08-15 per-track
 * manual mark, the one way past the automatic 0.75 ceiling (spectra/
 * services/intensity_scale_marks.py). auto_factor is always the un-marked
 * number (<= 1.25); effective_factor is what actually drives the room right
 * now (the mark, when set, else auto_factor). */
export interface IntensityScaleMark {
  uri: string;
  mark: number | null;
  auto_factor: number;
  effective_factor: number;
  manual_min: number;
  manual_max: number;
}

/** GET /api/sonic-usage — Sonic's REAL reported token usage (spectra/
 * services/sonic_usage.py), review page. `day`/`week` are fixed periods
 * anchored Monday 22:00 America/New_York (his own ruling, not rolling
 * windows) — each period_start_ms is the boundary the sums are since.
 * last_query is null when Sonic has never completed a turn with reported
 * usage; cost_usd is null when no recorded call in that slice reported a
 * cost (the "api" backend never does — see the service module docstring). */
export interface SonicUsagePeriod {
  query_count: number;
  total_tokens: number;
  input_tokens: number;
  output_tokens: number;
  cache_creation_input_tokens: number;
  cache_read_input_tokens: number;
  cost_usd: number | null;
  period_start_ms: number;
}

export interface SonicUsageLastQuery {
  wall_ms: number;
  backend: string;
  model: string;
  session_id: string | null;
  total_tokens: number;
  input_tokens: number;
  output_tokens: number;
  cache_creation_input_tokens: number;
  cache_read_input_tokens: number;
  cost_usd: number | null;
}

export interface SonicUsageSummary {
  last_query: SonicUsageLastQuery | null;
  day: SonicUsagePeriod;
  week: SonicUsagePeriod;
  as_of_ms: number;
  timezone: string;
  day_boundary_hour_local: number;
}
