/** Pure helpers for the Light Show's Playlists tab (PlaylistView.tsx) and
 * the Run view's playlist card (PlaylistRunCard.tsx), kept DOM-free so
 * scripts/check_show_playlist_ui.mjs can drive them directly. */
import type {
  PlaylistRun, PlaylistStep, PlaylistTiming, ShowPlaylist, SongEntry, StepOutcome,
} from './types';

export const TIMING_ORDER: PlaylistTiming[] = ['song_start', 'scene_change', 'high', 'low'];

/** The same glyphs as the Run view's one-tap row: bolt = as the song
 * starts, bunny = next scene change, up / down = this song's High / Low. */
export const TIMING_ICON: Record<PlaylistTiming, 'bolt' | 'rabbit' | 'arrowUp' | 'arrowDown'> = {
  song_start: 'bolt', scene_change: 'rabbit', high: 'arrowUp', low: 'arrowDown',
};

export const TIMING_LABEL: Record<PlaylistTiming, string> = {
  song_start: 'As the song starts',
  scene_change: 'Next scene change (the song\'s opening change counts)',
  high: 'This song\'s High Trigger',
  low: 'This song\'s Low Trigger',
};

export const TIMING_WORD: Record<string, string> = {
  song_start: 'song start', scene_change: 'next scene change', high: 'High Trigger', low: 'Low Trigger',
};

export function newId(): string {
  return Math.random().toString(16).slice(2, 14);
}

export function newStep(setId: string | null = null, on: PlaylistTiming = 'high'): PlaylistStep {
  return { id: newId(), set_id: setId, on, repeat: false, finish_on_mark: true, enabled: true };
}

export function newSong(uri: string, title: string, artist: string): SongEntry {
  return { id: newId(), uri, title, artist, steps: [], enabled: true };
}

export function newPlaylist(name = 'New playlist program'): ShowPlaylist {
  return {
    name, contexts: [], context_names: {}, auto_follow: true, follow_songs_anywhere: false,
    on_start: { sequence_id: null, replace_running_sequence: false, steps: [] },
    default_song: null, unlisted_song: 'default', songs: [],
    on_end: { steps: [], end_show: false },
  };
}

/** A copy of a song's entry for another song — every step a fresh id. */
export function copyEntrySteps(steps: PlaylistStep[]): PlaylistStep[] {
  return steps.map((s) => ({ ...s, id: newId(), title: undefined, problems: undefined }));
}

/** What the server is sent: served-only fields stripped. */
export function toWire(p: ShowPlaylist): ShowPlaylist {
  const step = ({ title: _t, problems: _p, ...s }: PlaylistStep) => s;
  const entry = ({ summary: _s, ...e }: SongEntry) => ({ ...e, steps: e.steps.map(step) });
  const { problems: _pr, ...rest } = p;
  return {
    ...rest,
    on_start: { ...p.on_start, steps: p.on_start.steps.map(step) },
    on_end: { ...p.on_end, steps: p.on_end.steps.map(step) },
    default_song: p.default_song ? entry(p.default_song) : null,
    songs: p.songs.map(entry),
  };
}

/** "spotify:playlist:abc" from a pasted Spotify link or URI; null when it
 * is neither a playlist nor an album. */
export function parseContext(text: string): string | null {
  const t = text.trim();
  const uri = /^spotify:(playlist|album|artist):([A-Za-z0-9]+)$/.exec(t);
  if (uri) return `spotify:${uri[1]}:${uri[2]}`;
  const url = /open\.spotify\.com\/(?:intl-[a-z-]+\/)?(playlist|album|artist)\/([A-Za-z0-9]+)/.exec(t);
  if (url) return `spotify:${url[1]}:${url[2]}`;
  return null;
}

export function contextLabel(p: ShowPlaylist, uri: string): string {
  return p.context_names[uri] || uri;
}

export function songWord(title: string, artist: string, uri?: string | null): string {
  const t = title || uri || 'a song';
  return artist ? `${t} — ${artist}` : t;
}

/** One step's outcome, in his words. */
export function outcomeLine(o: StepOutcome): string {
  const when = TIMING_WORD[o.on] ?? o.on;
  const at = o.at_ms ? ` ${new Date(o.at_ms).toLocaleTimeString()}` : '';
  switch (o.status) {
    case 'armed': return `${o.set_name} — armed for the ${when}${o.detail ? ` (${o.detail})` : ''}`;
    case 'pending': return `${o.set_name} — fires as the song starts`;
    case 'fired': return `${o.set_name} — fired${at}`;
    case 'missed': return `${o.set_name} — missed: ${o.detail || 'the song ended first'}`;
    case 'skipped': return `${o.set_name} — skipped`;
    case 'disarmed': return `${o.set_name} — disarmed${o.detail ? `: ${o.detail}` : ''}`;
    case 'refused': return `${o.set_name} — did not fire: ${o.detail}`;
    case 'failed': return `${o.set_name} — failed: ${o.detail}`;
    default: return `${o.set_name} — ${o.status}`;
  }
}

/** The Run card's headline: "Following 40! Lightshow · song 3". */
export function runHeadline(r: PlaylistRun): string {
  const state = r.state === 'following' ? 'Following' : r.state === 'paused' ? 'Paused' : r.state === 'stopped' ? 'Stopped' : 'Ended';
  const songs = r.songs_count ? ` · song ${r.songs_count}` : '';
  return `${state} ${r.name}${songs}`;
}

export function entryWord(source: string | null | undefined): string {
  return ({
    listed: 'its own entry', default: 'the default entry', none: 'nothing listed for it',
    off: 'its entry is switched off',
  } as Record<string, string>)[source ?? ''] ?? '';
}

/** Move one song (or step) in a list. */
export function reorder<T>(items: T[], from: number, to: number): T[] {
  const out = items.slice();
  const [it] = out.splice(from, 1);
  out.splice(Math.max(0, Math.min(out.length, to)), 0, it);
  return out;
}
