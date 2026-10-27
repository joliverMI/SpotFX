/** The Jukebox's master-side wire shapes — SpotFX's own /api/jukebox routes
 * (routers/jukebox_router.py; the engine is services/jukebox/night.py, the
 * rules services/jukebox/program.py). Field names are the server's. */

export type SlotMode = 'auto' | 'jukebox_first' | 'manual';
export type RunOut = 'again' | 'jukebox_only' | 'end';

export interface ManualSlot {
  after_uri: string;
  count: number;
}

export interface ProgramConfig {
  playlist: string;
  mode: SlotMode;
  every: number;
  run: number;
  manual: ManualSlot[];
  run_out: RunOut;
  commit_lead_s: number;
}

export interface SetItem {
  uri: string;
  title: string;
  artist: string;
  duration_ms: number;
}

/** One program item: a set song, a jukebox slot with the song filling it,
 * or an open slot (passes if nobody has a song waiting). */
export interface ProgramItem {
  kind: 'set' | 'jukebox' | 'open';
  uri: string;
  title: string;
  artist: string;
  duration_ms: number;
  set_index: number | null;
  entry_id: string;
  committed: boolean;
  starts_in_ms: number | null;
}

export interface Lap {
  set_songs: number;
  slots: number;
  unbounded: boolean;
  notes: string[];
}

export interface JukeboxPreview {
  status: 'ok' | 'refused';
  reason?: string;
  detail?: string;
  playlist_name?: string;
  playlist_uri?: string;
  set_songs?: number;
  set?: SetItem[];
  lap_items?: ProgramItem[];
  next?: ProgramItem[];
  manual_equivalent?: ManualSlot[];
  playhead?: number | null;
  lap?: Lap;
}

export type SignInState = 'no_token' | 'unknown' | 'ok' | 'soon' | 'expired' | 'refresh_failed' | 'unreadable';

export interface SpotifySignIn {
  state: SignInState;
  warning: string | null;
  authorized_at_ms?: number | null;
  expires_at_ms?: number | null;
  days_left?: number | null;
}

export interface NightBrief {
  id: string;
  state: 'running' | 'ended' | 'refused';
  started_ms: number;
  started_by: string;
  ended_ms: number | null;
  end_reason: string;
  end_detail: string;
  playlist_name: string;
  playlist_uri: string;
  played: number;
  jukebox_played: number;
}

export interface NowItem {
  kind: '' | 'set' | 'jukebox' | 'skipping' | 'foreign';
  uri: string;
  title: string;
  set_index: number | null;
  entry_id: string;
  started_ms: number | null;
}

export interface LineEntry {
  id: string;
  uri: string;
  title: string;
  artist: string;
  duration_ms: number;
  added_by: string;
  state: 'queued' | 'committed' | 'playing' | 'played' | 'removed' | 'skipped';
  doomed: boolean;
  commit_check: '' | 'next' | 'later' | 'missing' | 'unread';
}

export interface JukeboxStatus {
  night: NightBrief | null;
  running: boolean;
  now: NowItem | null;
  remaining_ms?: number;
  next: ProgramItem[];
  line: LineEntry[];
  lap?: Lap;
  warnings: string[];
  spotify_auth?: SpotifySignIn;
  log: string[];
  history: NightBrief[];
}

export interface SetMoveResult {
  status: 'moved' | 'refused';
  reason?: string;
  detail?: string;
  set?: SetItem[];
}

// ── the show settings (phase 3.3) ───────────────────────────────────────────

export type Preset = 'small' | 'medium' | 'large';

/** Every economy setting (models.jukebox.EconomyConfig), by key. */
export type EconomyConfig = Record<string, number | boolean>;

export interface ShowConfig {
  preset: Preset | null;
  approve_new_phones: boolean;
  economy: EconomyConfig;
}

/** One economy setting as the page draws it; the range is the server's
 * own model bound, never typed twice. */
export interface EconomyField {
  key: string;
  card: string;
  label: string;
  unit: string;
  kind: 'int' | 'float' | 'bool';
  default: number | boolean;
  min: number | null;
  max: number | null;
}

export interface PresetInfo {
  name: Preset;
  guests: string;
  why: string;
  approve_new_phones: boolean;
}

export interface ShowRead {
  show: ShowConfig;
  fields: EconomyField[];
  presets: PresetInfo[];
}

export interface PriceCheck {
  guests: number;
  add: { wait_min: number; price: number }[];
  add_long: { duration_min: number; price: number };
  add_not_learned: number;
  skip: { line_min: number; downs: number; price: number }[];
  play_next: { jump_min: number; price: number }[];
  bump_up: { behind: number; price: number }[];
  bump_down: { ahead: number; price: number }[];
  jail: { threshold: number; fee: number };
  start: { now: number; later: number; after_min: number };
  topup: { every_min: number; pauses_at: number };
  tips: { on: boolean; max_per_song: number; double_first: number };
  songs_in_line: number;
}
