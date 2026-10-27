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

export interface NowSong extends Song {
  votes: { up: number; down: number };
  my_vote: -1 | 0 | 1;
  can_vote: boolean;
  why_not: string;
  duration_ms: number;
  progress_ms: number;
  is_playing: boolean;
}

export interface NextSong extends Song {
  committed: boolean;          // already sent to Spotify: it plays next whatever happens
  starts_in_ms: number | null;
  duration_ms: number;
  place: number;               // 1 = the next song
  entry_id?: string;           // only on your own songs
}

export interface MySong extends Song {
  entry_id: string;
  state: 'playing' | 'next' | 'waiting';
  committed: boolean;
  place: number | null;
  starts_in_ms: number | null;
}

export type StripTone = 'none' | 'queued' | 'next' | 'playing';
export interface Strip {
  tone: StripTone;
  title: string;
  place: number | null;
  starts_in_ms: number | null;
  count: number;
}

export interface Features { add: boolean; board: boolean; credits: boolean }
export interface HowTile { icon: string; title: string; text: string }

export interface RunningView {
  state: 'running';
  server_ms: number;
  poll_ms: number;
  me: { name: string; joined: boolean; renames_left: number };
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
