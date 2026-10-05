/** HOUSE LIGHTING's wire shapes (spectra/models/house_mode.py and
 * spectra/services/house.py status_dict — keep these in step). */

export type MusicPolicy = 'show' | 'calm' | 'ignore';
export type MusicHue = 'hold' | 'join' | 'room';
export type HueLookKind = 'hold' | 'off' | 'show';
export type TargetKind = 'fixture' | 'category' | 'everything';

export interface HouseTarget { kind: TargetKind; id: string | null }
export interface ScenePick { scene_id: string; weight: number }
export interface ColorPick { card_id: string; weight: number }

export interface FixtureHook {
  target: HouseTarget;
  level: number | null;      // percent, 100 = unchanged
  motion: number | null;     // 0..1 position in the effect's motion range
  fps: number | null;        // a cap — only ever lowers
  off: boolean;
  music_level?: number | null; // percent while the music show has the room
}

export interface HueLook {
  area: string;              // a Hue area id, or "*" for every area
  look: HueLookKind;
  kelvin: number | null;
  color: string | null;
  brightness: number;        // 1..100
}

export interface HouseFlow { scene_every_min: number; journey_deg_per_min: number; intensity: number }
export interface HouseTransitions {
  clock_glide_s: number; button_glide_s: number;
  music_debounce_s: number; music_return_glide_s: number;
}

export interface HouseMode {
  id?: string;
  name: string;
  ha_aliases: string[];
  scenes: ScenePick[];
  color_sets: ColorPick[];
  flow: HouseFlow;
  fixtures: FixtureHook[];
  hue: HueLook[];
  music: MusicPolicy;
  music_hue: MusicHue;
  transitions: HouseTransitions;
  notes: string;
}

export interface HouseModesResponse {
  modes: HouseMode[];
  aliases: Record<string, string>;
  current_mode_id: string | null;
}

export interface HouseTargets {
  live: boolean;
  fixtures: { id: string; name: string; type: string }[];
  categories: { name: string; fixtures: string[] }[];
  hue_areas: { id: string; name: string }[];
}

export type HousePhase = 'inactive' | 'standby' | 'resting' | 'music';

/** The `lighting` key on GET /api/engine/status (and GET /api/house/mode). */
export interface LightingStatus {
  mode: { id: string; name: string } | null;
  source: string | null;
  since_ms: number | null;
  manual: boolean;
  manual_until?: string;
  ha_value: string | null;
  ha_value_ms: number | null;
  ha_mapped_mode: string | null;
  active: boolean;
  phase: HousePhase;
  reason: string;
  problems: string[];
  recent: { at_ms: number; kind: string; [k: string]: unknown }[];
  music?: { playing: boolean | null; policy: MusicPolicy; hue: MusicHue; returns_in_s: number | null };
  next_scene_in_s?: number | null;
  scene?: { id: string; name: string };
  fixtures?: { levels: Record<string, number>; off: string[]; caps: Record<string, number>;
    /** phase 3: WLEDs the mode switches off -> seconds until the switch-off */
    switching_off?: Record<string, number> };
  motion?: { virtual: string; param: string; value: number }[];
  hue?: { looks: { area: string; look: string; mirek: number | null; color: string | null; brightness: number }[] } | null;
  error?: string;
  // ── phase 2: the Home Assistant seam (spectra/services/house_fixtures.py,
  //    house_voice.py, house.py MEDIA) ──
  clock_mode?: { id: string; name: string } | null;
  media?: SeamMedia;
  tv_music?: boolean | null;
  seam_active?: boolean;
  seam_reason?: string | null;
  tv_strip?: SeamTvStrip;
  fixtures_seam?: SeamFixtures;
  voice?: SeamVoice;
  // ── phase 3: energy and network (spectra/services/house_energy.py) ──
  energy?: HouseEnergyStatus;
}

export interface HouseEnergySettings {
  resting_fps: Record<string, number>; park_idle: boolean; send_on_change: boolean;
  keepalive_s: number; audio_pause_after_s: number;
}

export interface HouseEnergyStatus {
  acting: boolean;
  settings: HouseEnergySettings;
  parking: boolean;
  parked: string[];
  send_on_change_s: number | null;
  audio: { state: 'listening' | 'paused' | 'off'; listeners: string[]; reason?: string;
    paused_for_s?: number; resume_error?: string; quiet_for_s: number | null };
  fixtures: Record<string, { id: string; sent_fps: number; skipped_fps: number; packets_per_s: number | null }>;
  packets_per_s_estimate: number | null;
  mains_off: Record<string, number>;
  recent: { at_ms: number; kind: string; [k: string]: unknown }[];
}

export interface SeamMedia {
  source: string | null; state: string | null; since_ms: number | null;
  active: boolean; mode: string | null; words: string[];
}

export interface SeamTvStrip { devices: string[]; owner: string; why: string | null; streaming: string[] }

export interface SeamFixture {
  device: string; name: string; target: 'on' | 'off' | 'lent' | 'unpowered' | null; why: string | null;
  in_flight: boolean;
  override: { power: 'on' | 'off' | null; lent_to: string | null; source: string; since_ms: number | null } | null;
  applied: { target: string; outcome: string; detail: string; at_ms: number } | null;
}

export interface SeamFixtures {
  acting: boolean; reason: string | null; own_brightness: boolean; owned_brightness: number;
  tv_music: boolean | null; fixtures: SeamFixture[]; withheld: Record<string, string>;
  corrections: { at_ms: number; device: string; target: string; found: { on: boolean | null; bri: number | null };
    set: Record<string, unknown>; outcome: string; detail: string }[];
  rechecks: Record<string, { state: string; attempts?: number; after_s?: number; reason?: string; moved?: boolean }>;
  mains_off?: Record<string, number>;
}

export interface SeamVoice {
  state: string; since_ms: number | null; fixtures: string[];
  skipped: { fixture: string; reason: string }[];
}

export interface SetModeResponse {
  status: 'applied' | 'unchanged' | 'held_manual' | 'unmapped' | 'unknown_mode' | 'cleared';
  reason?: string;
  lighting: LightingStatus;
}
