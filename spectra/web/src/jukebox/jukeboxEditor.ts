/** THE JUKEBOX SET-LIST EDITOR'S RULES AND WORDS — pure, no React, so
 * scripts/check_jukebox_editor.mjs drives them directly.
 *
 * The click rules are the plan's (data/jukebox-plan/report.md §5):
 *   - click a SET SONG     → a jukebox slot right after it (if it has none)
 *   - click a JUKEBOX SLOT → another slot right after it (two in a row;
 *                            click again for three — never more)
 *   - a slot's ×           → that one slot goes
 * Slots follow a song by its URI (models/jukebox.py's ManualSlot), so they
 * stay with it when the set is reordered.
 *
 * WHERE the slots are is never computed here: the server's projection
 * (services/jukebox/program.py, the one definition the engine itself uses)
 * arrives as `lap_items` — one pass through the set with every slot shown —
 * and `slotsByIndex` only counts what it says. Switching Auto to Manual
 * copies the server's own `manual_equivalent`, so the copy is exactly the
 * pattern that was playing. */
import type {
  JukeboxStatus, LineEntry, Lap, ManualSlot, NightBrief, ProgramConfig, ProgramItem, RunOut,
  SlotMode, SpotifySignIn,
} from './types';

export const MAX_RUN = 3;
/** An unknown jukebox song's length on the program bar: his library's median. */
export const SLOT_BAR_S = 215;
export const GUEST_COUNTS = [4, 8, 15, 30] as const;

// ── the click rules ──────────────────────────────────────────────────────────

export function slotsAfter(manual: ManualSlot[], uri: string): number {
  return manual.find((m) => m.after_uri === uri)?.count ?? 0;
}

/** Click a set song: a slot after it, if it has none yet. */
export function clickSetSong(manual: ManualSlot[], uri: string): ManualSlot[] {
  if (slotsAfter(manual, uri) > 0) return manual;
  return [...manual, { after_uri: uri, count: 1 }];
}

/** Click a jukebox slot: another one right after it, up to MAX_RUN. */
export function clickSlot(manual: ManualSlot[], uri: string): ManualSlot[] {
  const n = slotsAfter(manual, uri);
  if (n === 0 || n >= MAX_RUN) return manual;
  return manual.map((m) => (m.after_uri === uri ? { ...m, count: n + 1 } : m));
}

/** A slot's ×: one slot fewer after that song; the last one takes the run. */
export function removeSlot(manual: ManualSlot[], uri: string): ManualSlot[] {
  const n = slotsAfter(manual, uri);
  if (n === 0) return manual;
  if (n === 1) return manual.filter((m) => m.after_uri !== uri);
  return manual.map((m) => (m.after_uri === uri ? { ...m, count: n - 1 } : m));
}

/** Moving a set song in the list: the new index for a drag from `from` to
 * `to` (both indices in the CURRENT list), and the new order. */
export function moved<T>(items: T[], from: number, to: number): T[] {
  const out = [...items];
  const [it] = out.splice(from, 1);
  out.splice(to, 0, it);
  return out;
}

/** During a night, only set songs at least two ahead of the one playing may
 * move (the server refuses the rest; the editor says so before he tries). */
export function canMove(index: number, playhead: number | null | undefined): boolean {
  return playhead == null || index >= playhead + 2;
}

// ── reading the server's projection ─────────────────────────────────────────

/** How many slots follow each set song in one pass (index = set position). */
export function slotsByIndex(lapItems: ProgramItem[], setLength: number): number[] {
  const out = new Array<number>(setLength).fill(0);
  let at: number | null = null;
  for (const it of lapItems) {
    if (it.kind === 'set') at = it.set_index;
    else if (at != null && at < setLength) out[at] += 1;
  }
  return out;
}

export interface BarSegment {
  kind: 'set' | 'slot';
  /** seconds — the segment's share of the bar */
  weight: number;
  index: number | null;
  current: boolean;
  title: string;
}

/** The program bar: one pass of the set, set songs by length, each slot at
 * the median song length, the playing set song marked. */
export function barSegments(lapItems: ProgramItem[], playhead: number | null | undefined): BarSegment[] {
  return lapItems.map((it) => it.kind === 'set'
    ? { kind: 'set' as const, weight: Math.max(30, Math.round(it.duration_ms / 1000)),
        index: it.set_index, current: playhead != null && it.set_index === playhead,
        title: it.title }
    : { kind: 'slot' as const, weight: SLOT_BAR_S, index: null, current: false, title: 'Jukebox slot' });
}

export function countLine(lap: Lap | undefined, guests: number): string {
  if (!lap) return '';
  const songs = `${lap.set_songs} set song${lap.set_songs === 1 ? '' : 's'}`;
  if (lap.unbounded && lap.slots === 0) {
    return `${songs} · jukebox first: as many slots as the line holds`;
  }
  const slots = `${lap.slots} jukebox slot${lap.slots === 1 ? '' : 's'}`;
  const extra = lap.unbounded ? ', then as many as the line holds' : '';
  if (lap.slots === 0) return `${songs} · no jukebox slots${extra}`;
  const per = (lap.slots / Math.max(1, guests)).toFixed(1);
  return `${songs} · ${slots}${extra} ≈ ${per} per guest at ${guests} guests`;
}

// ── words ────────────────────────────────────────────────────────────────────

export const MODE_LABEL: Record<SlotMode, string> = {
  auto: 'Auto',
  jukebox_first: 'Jukebox first',
  manual: 'Manual',
};

export const RUN_OUT_LABEL: Record<RunOut, string> = {
  again: 'Play the set again',
  jukebox_only: 'Jukebox songs only',
  end: 'End the night',
};

export function ruleLine(cfg: ProgramConfig): string {
  if (cfg.mode === 'jukebox_first') {
    return 'The set only plays when nobody has a song waiting.';
  }
  if (cfg.mode === 'manual') {
    const n = cfg.manual.reduce((a, m) => a + m.count, 0);
    return n === 0
      ? 'No slots yet — click a set song to put a jukebox slot after it.'
      : `${n} slot${n === 1 ? '' : 's'} placed by hand. Click a set song for a slot after it, a slot for another right after it.`;
  }
  const after = cfg.every === 1 ? 'every set song' : `every ${cfg.every} set songs`;
  const run = cfg.run === 1 ? 'A jukebox slot' : `${cfg.run} jukebox slots in a row`;
  return `${run} after ${after}. An empty slot passes and the set continues.`;
}

export function mmss(ms: number | null | undefined): string {
  const s = Math.max(0, Math.round((ms ?? 0) / 1000));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const ss = String(s % 60).padStart(2, '0');
  return h > 0 ? `${h}:${String(m).padStart(2, '0')}:${ss}` : `${m}:${ss}`;
}

export function startsIn(ms: number | null | undefined): string {
  return ms == null ? '' : ms <= 0 ? 'next' : `in ${mmss(ms)}`;
}

export interface ItemView {
  tag: string;
  title: string;
  sub: string;
  tone: 'set' | 'jukebox' | 'open';
}

export function itemView(it: ProgramItem): ItemView {
  if (it.kind === 'set') {
    return { tag: `Set ${(it.set_index ?? 0) + 1}`, title: it.title || it.uri, sub: it.artist, tone: 'set' };
  }
  if (it.kind === 'jukebox') {
    return { tag: 'Jukebox', title: it.title || it.uri,
             sub: [it.artist, it.committed ? 'sent to Spotify' : ''].filter(Boolean).join(' · '),
             tone: 'jukebox' };
  }
  return { tag: 'Jukebox', title: 'Open slot', sub: 'passes if nobody has a song waiting', tone: 'open' };
}

const NOW_TAG: Record<string, string> = {
  set: 'Set', jukebox: 'Jukebox', skipping: 'Skipping', foreign: 'Off the set',
};

export function nowLine(status: JukeboxStatus | undefined): { tag: string; title: string } | null {
  const now = status?.now;
  if (!status?.running || !now || !now.kind) return null;
  const tag = now.kind === 'set' && now.set_index != null
    ? `Set ${now.set_index + 1}` : NOW_TAG[now.kind] ?? now.kind;
  return { tag, title: now.title || now.uri };
}

const clock = (ms: number | null | undefined) =>
  ms ? new Date(ms).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '';

export function nightLine(night: NightBrief | null | undefined): string {
  if (!night) return 'No night yet. A night is started for the daytime test (G1); the guest page comes in phase 2.';
  const on = night.playlist_name ? ` on ${night.playlist_name}` : '';
  const played = `${night.played} played, ${night.jukebox_played} from the jukebox`;
  if (night.state === 'running') return `Running since ${clock(night.started_ms)}${on} — ${played}.`;
  if (night.state === 'refused') return `The last start was refused at ${clock(night.started_ms)}: ${night.end_detail}`;
  return `The last night${on} ended at ${clock(night.ended_ms)}: ${night.end_detail} (${played}).`;
}

export function entryLine(e: LineEntry): string {
  if (e.state === 'playing') return 'playing now';
  if (e.state === 'committed') {
    if (e.doomed) return 'removed — skipped as it starts';
    return e.commit_check === 'later' ? 'sent to Spotify — songs added in Spotify play first'
      : e.commit_check === 'missing' ? 'sent — Spotify’s queue doesn’t show it yet'
      : 'sent to Spotify, plays next';
  }
  return `waiting · added by ${e.added_by}`;
}

export interface SignInView {
  text: string;
  tone: 'warn' | 'danger';
}

/** The Spotify sign-in line (PR 1.2's warning): shown only when one is due. */
export function signInView(s: SpotifySignIn | undefined): SignInView | null {
  if (!s || !s.warning || s.state === 'ok') return null;
  const danger = s.state === 'expired' || s.state === 'refresh_failed' || s.state === 'no_token';
  return { text: s.warning, tone: danger ? 'danger' : 'warn' };
}

/** The night's own warnings, without the sign-in line the page shows apart. */
export function nightWarnings(status: JukeboxStatus | undefined): string[] {
  const sign = status?.spotify_auth?.warning;
  return (status?.warnings ?? []).filter((w) => w !== sign);
}
