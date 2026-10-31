/** The Absorbing tab's words (absorb-then-queue, phase 4 —
 * services/jukebox/learning.py is the binding statement), pure so
 * scripts/check_jukebox_absorbing.mjs drives them directly. Nothing here
 * invents a number: every time is the server's own estimate
 * (`eta_s`, from the hidden player's measured outcomes), and an estimate the
 * server didn't give is shown as none rather than guessed. */
import type { LearnState, LearningRow, LearningStatus, LineEntry } from './types';

/** "ready in ~4 min" from the server's seconds; null → no estimate. */
export function etaWords(eta_s: number | null | undefined): string {
  if (eta_s === null || eta_s === undefined) return 'no estimate yet';
  if (eta_s < 60) return 'ready in under a minute';
  return `ready in ~${Math.round(eta_s / 60)} min`;
}

/** Where one song stands, in a few words. */
export function stateWords(state: LearnState['state'], why: string = ''): string {
  switch (state) {
    case 'learning': return 'being learned now';
    case 'waiting': return 'waiting to be learned';
    case 'parked': return "couldn't be learned";
    case 'learned': return 'learned';
    case 'unanalysed': return why === 'dry' ? 'playing un-analysed (nothing else would play)'
      : 'playing un-analysed (you let it through)';
  }
}

/** The tab's first line: can the hidden player learn tonight, and if not,
 * the server's own reason (which also says what happens instead). */
export function headline(st: LearningStatus | undefined, running: boolean): string {
  if (!st) return 'Reading the hidden player…';
  if (!running) return 'The hidden player learns new songs while a night runs.';
  if (!st.learn_first) return 'Learning first is off: new songs play straight away, un-analysed, and are learned as they play.';
  if (!st.available) return st.reason || "The hidden player can't learn right now, so new songs play un-analysed.";
  const n = st.queue.length;
  if (n === 0) return 'Every song in line is ready: nothing is waiting to be learned.';
  return `${n} ${n === 1 ? 'song is' : 'songs are'} being learned or waiting, one at a time.`;
}

/** How far through the song being learned the hidden player is (0-1), or
 * null when the server didn't say. */
export function progress(st: LearningStatus | undefined): number | null {
  const job = st?.lane.job;
  if (!job || !job.duration_ms || st?.lane.progress_ms === null || st?.lane.progress_ms === undefined) return null;
  return Math.max(0, Math.min(1, st.lane.progress_ms / job.duration_ms));
}

/** The try a song is on ("1st try", "2nd try") — shown from the 2nd on. */
export function tryWords(row: Pick<LearningRow, 'attempts' | 'state'>): string {
  if (row.state === 'parked' || row.attempts <= 0) return '';
  const n = row.attempts + 1;
  return `${n === 2 ? '2nd' : n === 3 ? '3rd' : `${n}th`} try`;
}

/** Why a parked song couldn't be learned, in the lane's own words. */
export function failWords(row: LearningRow, sentences: Record<string, string> = {}): string {
  const said = sentences[row.reason] || row.reason || 'it failed';
  return `${row.attempts} ${row.attempts === 1 ? 'try' : 'tries'}: ${said}`;
}

/** The buttons a row offers the host. */
export function rowActions(row: LearningRow): ('unanalysed' | 'relearn')[] {
  if (row.state === 'parked') return ['relearn', 'unanalysed'];
  if (row.state === 'waiting' || row.state === 'learning') return ['unanalysed'];
  return [];
}

/** The tab's small print: what each estimate is built from. */
export function numbersWords(st: LearningStatus | undefined): string {
  if (!st) return '';
  const pct = Math.round(st.numbers.success * 100);
  return `Each song takes its own length plus about ${st.numbers.overhead_s} s to set up and analyse; `
    + `about ${pct}% learn on the first try.`;
}

/** The badge a song in the jukebox line carries while it waits to be
 * learned (the Live and Guests tabs), or null when it is ready. */
export function lineBadge(e: Pick<LineEntry, 'state' | 'known' | 'learn' | 'ready'>): string | null {
  if (e.state !== 'queued' || e.known || !e.learn) return null;
  switch (e.learn.state) {
    case 'learning': return 'learning';
    case 'waiting': return e.ready === false ? 'waiting to learn' : null;
    case 'parked': return "couldn't learn";
    case 'unanalysed': return 'un-analysed';
    default: return null;
  }
}
