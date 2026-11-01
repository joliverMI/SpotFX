/** The shape of `GET /api/jukebox/tv` (services/jukebox/guests.py::
 * Guests.tv_view, data/tv-display-plan/plan.html PR 1.3), as relayed
 * verbatim in the feed's `jukebox` message (spectra/services/
 * tv_feed.py::jukebox_message). One definition, read by the Party screen
 * (PR 1.4) and the up-next callout. */
export interface ByAttribution {
  kind: 'set' | 'host' | 'guest';
  name: string;
}

export interface NowPlaying {
  uri: string;
  title: string;
  artist: string;
  image: string;
  thumb: string;
  open_url: string;
  by: ByAttribution;
  up: number;
  down: number;
  duration_ms: number;
  progress_ms: number;
  is_playing: boolean;
}

export interface NextItem {
  uri: string;
  title: string;
  artist: string;
  image: string;
  thumb: string;
  by: ByAttribution;
  starts_in_ms: number | null;
}

export interface BoardSong {
  uri: string;
  title: string;
  artist: string;
  image: string;
  thumb: string;
  by: ByAttribution;
  ups: number;
  downs: number;
  plays: number;
  mine: boolean;
  kind: string;
  open_url: string;
}

export interface Board {
  title: string;
  empty: string;
  songs: BoardSong[];
  people: unknown[];
}

export interface JukeboxView {
  running: boolean;
  reachable: boolean;
  now: NowPlaying | null;
  next: NextItem[];
  board: Board | null;
  link: string | null;
  revision?: number;
}

/** A loose runtime check — the feed's `jukebox` message is JSON from the
 * network, never trusted blindly. Only checks the fields the Party screen
 * actually reads; a payload failing this renders nothing rather than
 * crashing on a malformed message. */
export function isJukeboxView(v: unknown): v is JukeboxView {
  if (!v || typeof v !== 'object') return false;
  const o = v as Record<string, unknown>;
  return typeof o.running === 'boolean' && Array.isArray(o.next);
}
