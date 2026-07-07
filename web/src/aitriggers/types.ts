/** TS mirrors for the AI Triggers page (frontend/ai_triggers.html). */

export interface Suggestion {
  timestamp_ms: number;
  event_id: string;
  event_name?: string;
  confidence: number;
  reasoning: string;
  original_timestamp_ms: number;
  original_event_id: string;
  labels: string[];
  comment: string;
  manually_added: boolean;
  approved: boolean | null;
}

export interface CachedSet {
  title: string;
  artist: string;
  songComment: string;
  duration_ms: number;
  generated_at: string;
  training_profile_id: string;
  training_profile_name: string;
  applied: boolean;
  cost_usd?: number;
  input_tokens?: number;
  output_tokens?: number;
  suggestions: Suggestion[];
}

export interface SongInfo {
  uri: string;
  title: string;
  artist: string;
  duration_ms?: number;
  trigger_count?: number;
  mark_count?: number;
  has_suggestions?: boolean;
  genres?: string[];
}

export interface TrainingProfile {
  id: string;
  name: string;
  description?: string;
  genres?: string[];
  is_default?: boolean;
  notes?: string;
  training_uris?: string[];
  embedded_only_uris?: string[];
  target_uris?: string[];
  [k: string]: unknown;
}

export interface SavedSetSummary {
  track_id: string;
  spotify_uri: string;
  title: string;
  artist: string;
  suggestion_count: number;
  generated_at?: string;
  reviewed?: boolean;
  applied?: boolean;
  training_profile_name?: string;
  duration_ms?: number;
}

export interface CostEstimate {
  per_song: {
    uri: string; title?: string; artist?: string; error?: string;
    input_tokens: number; output_tokens: number;
  }[];
  total_input_tokens: number;
  total_output_tokens: number;
  total_haiku_cost_usd: number;
  total_sonnet_cost_usd: number;
}

/** Embedded trigger settings slots — [field prefix or full key, label, kind]. */
export const TP_EVENT_SLOTS: [string, string, string][] = [
  ['lull_event_id', 'Lull Event', 'Fires at the first quiet beat before a drop (start of the gap). Empty = skip.'],
  ['drop_event_id', 'Bass Drop Event', 'Fires at the re-entry beat after the gap (bass comes back in). Empty = skip.'],
  ['charge_event_id', 'Charge Event', 'Fires at peak energy/onset before each lull — the climax of the buildup. Empty = skip.'],
  ['quiet_event_id', 'Quiet Section Event', 'Fires at the start of extended quiet sections (breakdown, bridge). Empty = skip.'],
  ['scene_fill_event_id', 'Scene Fill Event', 'Used for beat start and standard fill (energy uptick / harmonic / downbeat). Empty = skip.'],
  ['song_start_event_id', 'Song Start Event', ''],
  ['beat_start_event_id', 'Beat Start Event', 'Fired at the first significant bass entry. If empty, falls back to Scene Fill Event.'],
  ['song_end_event_id', 'Song End Event', ''],
  ['flare_event_id', 'Flare Event', 'Event placed at harmonic moments throughout the song. Empty = skip flare stage.'],
];

export function fmtTs(ms: number): string {
  const s = Math.floor(ms / 1000);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}.${String(ms % 1000).slice(0, 1)}`;
}

export function parseTsInput(str: string): number | null {
  const m = str.trim().match(/^(\d+):(\d{1,2})(?:\.(\d))?$/);
  if (!m) return null;
  return (parseInt(m[1]) * 60 + parseInt(m[2])) * 1000 + (m[3] ? parseInt(m[3]) * 100 : 0);
}

export const isModified = (s: Suggestion) =>
  s.timestamp_ms !== s.original_timestamp_ms || s.event_id !== s.original_event_id;

export const confColor = (c: number) => (c >= 0.8 ? '#4caf50' : c >= 0.6 ? '#ff9800' : '#ef5350');

export function markerColor(s: Suggestion): string {
  if (s.manually_added) return '#1565c0';
  if (s.approved === true) return '#4caf50';
  if (s.approved === false) return 'rgba(239,83,80,0.5)';
  return 'rgba(255,255,255,0.5)';
}
