// The guest page's view of the night — exactly what SpotFX's
// services/jukebox/guests.py `build_view` sends (via the guest app,
// jukebox_guest/). Other phones appear by NAME only.

export type ByKind = 'set' | 'host' | 'guest' | 'other';
export interface By { kind: ByKind; name: string }

export interface Song {
  kind: 'set' | 'jukebox' | 'other';
  uri: string;
  title: string;
  artist: string;
  image: string;       // Spotify's own album art (shown unaltered), '' when none
  thumb: string;
  open_url: string;    // Spotify's page for the song
  by: By;
  mine: boolean;
}

/** Free play's skip on the song playing: N ▼ and that share of the votes. */
export interface SkipInfo {
  downs_at: number;
  share: number;               // percent
  rule: string;                // "3 ▼ and two-thirds of the votes skip a song"
  needed: number;              // more ▼ that skip it (0: the room has voted it off)
  skipping: boolean;           // it is being skipped now
  grace_left_ms: number;       // no skip in a song's first seconds
}

export interface NowSong extends Song {
  votes: { up: number; down: number };
  my_vote: -1 | 0 | 1;
  can_vote: boolean;
  why_not: string;
  duration_ms: number;
  progress_ms: number;
  is_playing: boolean;
  skip?: SkipInfo;             // set and jukebox songs (free play)
}

export interface NextSong extends Song {
  committed: boolean;          // already sent to Spotify: it plays next whatever happens
  starts_in_ms: number | null;
  duration_ms: number;
  place: number;               // 1 = the next song
  known?: boolean;             // the lights already know it
  entry_id?: string;           // jukebox songs (an id for the song, never a phone)
  bump?: 'up' | 'down' | null; // what you may do to it: your own up, others' down
  bump_why?: string;           // why it can't move, when it can't
}

export interface MySong extends Song {
  entry_id: string;
  state: 'playing' | 'next' | 'waiting';
  committed: boolean;
  held: boolean;               // the host is holding it: it keeps its place
  jailed?: boolean;            // it sits out your time-out (keeps its place)
  known: boolean;
  place: number | null;
  starts_in_ms: number | null;
}

export type StripTone = 'none' | 'queued' | 'next' | 'playing' | 'jail';
export interface Strip {
  tone: StripTone;
  title: string;
  place: number | null;
  starts_in_ms: number | null;
  held: boolean;
  count: number;
  jail_left?: number;
}

/** The jail (free play): a time-out of N songs when your songs get the
 *  bar's net ▼. */
export interface JailInfo { in: boolean; songs_left: number; count: number; at: number; on: boolean }
/** Bumps this hour. */
export interface BumpsInfo { per_hour: number; left: number; next_at: string | null }

/** Tonight's requests: open until last call; songs in line per guest. */
export interface Requests {
  open: boolean;
  closes_at: string;           // "11:40", house time
  ends_at: string;
  closes_at_ms: number;
  ends_at_ms: number;
  detail: string;              // why they're closed, when they are
  max_waiting: number;
  waiting: number;             // yours, in line now
}

/** One search result as the Add screen draws it. */
export interface SearchResult {
  uri: string;
  title: string;
  artist: string;
  image: string;
  thumb: string;
  duration_ms: number;
  explicit: boolean;
  open_url: string;
  known: boolean;              // "Ready": the lights already know it
  library: boolean;            // from his own library
  long: boolean;
  in_line: boolean;
  can_add: boolean;
  why_not: string;
}

export interface Features { add: boolean; board: boolean; credits: boolean }
export interface HowTile { icon: string; title: string; text: string }

export interface RunningView {
  state: 'running';
  server_ms: number;
  poll_ms: number;
  me: { name: string; joined: boolean; approved: boolean; name_locked: boolean; renames_left: number;
        jail?: JailInfo; bumps?: BumpsInfo };
  requests: Requests;
  features: Features;
  house_rules: string[];
  privacy: string;
  how: HowTile[];
  now: NowSong | null;
  next: NextSong[];
  mine: MySong[];
  strip: Strip;
}

export interface IdleView {
  state: 'idle';
  server_ms: number;
  poll_ms: number;
  detail: string;
  house_rules: string[];
  privacy: string;
}

export type View = RunningView | IdleView;

export interface Refusal { status: 'refused'; reason: string; detail: string }
