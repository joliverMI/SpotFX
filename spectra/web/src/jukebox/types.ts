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
