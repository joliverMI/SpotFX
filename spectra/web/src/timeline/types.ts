/** TS mirrors for the Profile Builder — models/song_profile.py,
 * models/audio_shape.py, models/librosa_analysis.py, palettes. */

export interface MusicTrigger {
  id: string;
  timestamp_ms: number;
  event_id: string;
  labels: string[];
  enabled: boolean;
  intensity: number; // 0-1, 0.5 = mid (the draggable circle)
  // Override Blend: stretch/compress the event's ramps + delays so it
  // completes exactly at the next enabled trigger (or song end).
  override_blend?: boolean;
  // Scene-group color override: ColorSetCard id (kind "group") used instead of
  // the scene group's designated Color Group when this trigger fires one.
  color_group_override?: string | null;
  // Dark/Light override for this fire ('default' = defer down the cascade).
  display_mode?: 'default' | 'dark' | 'light';
  // Drop fallback override: scene_group event id used by the fixed Drop
  // event's clean-transition / random-member fallback instead of the global
  // drop group. null/missing = normal behavior.
  drop_scene_group_override?: string | null;
  // joined by GET /profiles/current only:
  event_name?: string;
  event_color?: string;
}

export interface SongProfile {
  spotify_uri: string;
  title: string;
  artist: string;
  artist_genre: string | null;
  duration_ms: number;
  labels: string[];
  verified: boolean;
  notes: string;
  triggers: MusicTrigger[];
  setlist_triggers: Record<string, MusicTrigger[]>;
  audio_shape_file: string | null;
  [k: string]: unknown; // AI-provenance + future fields pass through untouched
}

export type MarkType =
  | 'bass_drop' | 'bass_start' | 'bass_end' | 'power_up' | 'power_down'
  | 'quiet' | 'charging' | 'tempo_change';

export interface MusicMark {
  ms: number;
  type: MarkType;
  [k: string]: unknown;
}

export interface AudioShapeMeta {
  spotify_uri: string;
  title: string;
  artist: string;
  duration_ms: number;
  sample_interval_ms: number;
  music_marks: MusicMark[];
  capture_complete: boolean;
  timestamp_offset_ms: number;
  perception_trim_ms: number;
  offset_verification: 'unverified' | 'auto_verified' | 'user_verified';
  offset_quality: number;
  [k: string]: unknown;
}

export interface AudioShapeData {
  timestamps_ms: number[];
  rms_total: number[];
  rms_low: number[];
  rms_mid: number[];
  rms_high: number[];
  avg_rms_1s: number[] | null; // stored smoothed envelope (old captures: null)
}

export interface LibrosaBeat {
  ms: number;
  is_downbeat: boolean;
  rms_total: number;
  rms_bass: number;
  rms_mid?: number;
  rms_high?: number;
  onset_score: number;
  bass_onset_score?: number;
  snare_onset_score?: number;
  harmonic_score?: number;
  [k: string]: unknown;
}

export interface LibrosaSection {
  start_ms: number;
  end_ms: number;
  label: string;
  energy_rms: number;
  onset_density_per_s: number;
}

export interface LibrosaAnalysis {
  tempo_bpm: number;
  offset_ms?: number;
  beats: LibrosaBeat[];
  onsets: { ms: number; strength?: number; kind?: string }[];
  sections: LibrosaSection[];
  harmonic_changes?: { ms: number; novelty?: number }[];
  mfcc_changes?: { ms: number; distance?: number }[];
  [k: string]: unknown;
}

export interface Palette {
  id: string;
  name: string;
  color: string;
  keys: Record<string, string | null>; // keychar → event_id
}

export interface Setlist {
  id: string;
  name: string;
  [k: string]: unknown;
}

/** Trimmed event info for pickers (from GET /api/events). */
export interface EventOption {
  id: string;
  name: string;
  color: string;
  event_type?: string;
}
