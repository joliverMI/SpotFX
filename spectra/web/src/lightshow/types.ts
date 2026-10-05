/** Wire shapes for /api/light-show (spectra/api/light_show.py). The
 * catalogue is SERVED, not hard-coded here: every action kind declares its
 * own params (spectra/services/show_actions.py), and the editor renders
 * whatever it is given — a new kind needs no frontend change. */

export interface ShowParam {
  name: string;
  type: string;
  label: string;
  default: unknown;
  required: boolean;
  choices: string[] | null;
  min: number | null;
  max: number | null;
  unit: string;
  help: string;
}

export interface ShowKind {
  kind: string;
  label: string;
  group: 'setting' | 'device' | 'effect' | 'control';
  params: ShowParam[];
  help: string;
  restore: string;
  help_topic: string;
}

export interface ShowCatalogue {
  kinds: ShowKind[];
  room_effects: { id: string; name: string; kind: string; room_id: string }[];
  room_effect_schema: { properties?: Record<string, { type?: string; minimum?: number; maximum?: number; title?: string }> } | null;
}

export interface ShowAction {
  id?: string;
  kind: string;
  params: Record<string, unknown>;
  label?: string;
  enabled?: boolean;
}

export interface ShowSet {
  id?: string;
  name: string;
  actions: ShowAction[];
  notes?: string;
  problems?: string[];
  conflicts?: string[];
}

export interface ShowTargets {
  live: boolean;
  fixtures: { id: string; name: string; type: string; held_by_ambient: boolean }[];
  categories: { name: string; fixtures: string[] }[];
}

export interface ShowStep {
  action_id: string;
  kind: string;
  label: string;
  status: 'pending' | 'waiting' | 'applied' | 'skipped' | 'refused' | 'failed';
  detail: string;
}

export interface ShowRun {
  id: string;
  name: string;
  set_id: string | null;
  source: string;
  started_ms: number;
  ended_ms: number | null;
  state: 'running' | 'done' | 'partial' | 'failed' | 'refused' | 'cancelled';
  steps: ShowStep[];
}

export interface ShowBrief {
  active: boolean;
  holds: number;
  levels: number;
  running_sets: number;
  room_effect: string | null;
  changed_settings: number;
  /** waiting arms (phase 2) */
  armed?: number;
  standdown: string | null;
  refusal: string | null;
}

export interface ShowStatus {
  active: boolean;
  started_ms: number | null;
  baselines: { key: string; label: string; original: unknown; written: unknown }[];
  room_effect: { name: string; started_ms: number; duration_s: number } | null;
  running_sets: ShowRun[];
  recent_runs: ShowRun[];
  output: {
    holds: { device: string; name: string; state: string; held_by_ambient: boolean }[];
    levels: { id: string; names: string[]; level: number; until: string; remaining_s: number | null }[];
    suspended: boolean;
    standdown: string | null;
    refusal: string | null;
  };
  brief: ShowBrief;
}

export interface EndShowReport {
  cancelled_runs: string[];
  room_effect_stopped: boolean;
  released_devices: string[];
  restored: string[];
  left_alone: { key: string; label: string; reason: string }[];
  failed: { key: string; label: string; reason: string }[];
}

// ── PHASE 2: arms and the High/Low Triggers (spectra/services/show_arms.py,
//    show_cues.py) ──────────────────────────────────────────────────────────

export type ArmTrigger = 'scene_change' | 'high' | 'low';

export interface ShowArm {
  id: string;
  set_id: string | null;
  action: ShowAction | null;
  label: string;
  on: ArmTrigger | string;
  repeat: boolean;
  song_uri: string | null;
  source: string;
  finish_on_mark: boolean;
  created_ms: number;
  expires_ms: number | null;
  status: 'armed' | 'fired' | 'missed' | 'disarmed' | 'expired';
  fire_count: number;
  ended_ms: number | null;
  end_reason: string;
  last_outcome: { status: string; reason?: string; at_ms?: number; trigger?: string } | null;
  /** status only (armed rows) */
  lead_ms?: number;
  this_song?: boolean;
  due_ms?: number | null;
}

export interface ShowCue {
  level: 'high' | 'low';
  timestamp_ms: number;
  source: 'auto' | 'drop_mark' | 'moved';
  shift: number | null;
  auto_ms: number | null;
  auto_shift: number | null;
  drop_mark_ms: number | null;
  alternates: { timestamp_ms: number; shift: number; close: boolean }[];
  runner_up_close: boolean;
  moved_ms: number | null;
}

export interface SongCues {
  uri: string;
  reason: string | null;
  duration_ms: number | null;
  high: ShowCue | null;
  low: ShowCue | null;
}

export interface ArmsStatus {
  armed: ShowArm[];
  history: ShowArm[];
  song: {
    uri: string | null; position_ms: number | null; cues: SongCues | null;
    /** The showing scene's own minimum-hold FLOOR (dwell.py) in seconds —
     * null when nothing is tracked. Not a real prediction of when a scene
     * actually changes, only the earliest it could. */
    expected_scene_change_s: number | null;
    expected_scene_change_is_floor: boolean;
  };
  last_crossed: Record<string, { uri: string | null; cue_ms: number; at_ms: number }>;
  refusal: string | null;
}
