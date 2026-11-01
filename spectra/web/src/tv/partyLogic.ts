/** Pure logic for the Party screen (data/tv-display-plan/plan.html PR
 * 1.4) — progress interpolation, the up-next callout's timing rule, and
 * time formatting. No DOM, so scripts/check_tv_party.mjs can drive it
 * with synthetic clocks. */
import { NextItem, NowPlaying } from './jukeboxTypes';

/** `now.progress_ms` is a snapshot from the last ~1 Hz relay push
 * (tv_feed.py's jukebox_loop); interpolate forward by elapsed client time
 * while actually playing, the same shape clock.ts's show-clock
 * interpolation already uses and for the identical reason (the push
 * cadence is not the frame cadence). Clamped to the song's own length —
 * a late next push must never show progress running past 100%. */
export function interpolatedProgressMs(now: NowPlaying, receivedAtMs: number | null,
                                      nowMs: number): number {
  if (!now.is_playing || receivedAtMs === null) return now.progress_ms;
  const elapsed = Math.max(0, nowMs - receivedAtMs);
  return Math.min(now.duration_ms, now.progress_ms + elapsed);
}

export function remainingMs(now: NowPlaying, progressMs: number): number {
  return Math.max(0, now.duration_ms - progressMs);
}

/** Plan §2.2: "the callout in the last 30 s of a song once the next song
 * is sent to Spotify". `next` already excludes "open" (unfilled) slots —
 * `tv_view()`'s own filter (services/jukebox/guests.py) — so a non-empty
 * `next` already means a real next song is known; this just adds the
 * 30 s window. */
const CALLOUT_WINDOW_MS = 30_000;

export function showCallout(now: NowPlaying | null, next: NextItem[], progressMs: number): boolean {
  if (!now || next.length === 0) return false;
  return remainingMs(now, progressMs) <= CALLOUT_WINDOW_MS;
}

/** "2:07" / "0:08" — never a fraction of a second (the plan's mockup's
 * own progress line, §2.1: "2:07 ... 3:51"). */
export function fmtMMSS(ms: number): string {
  const totalS = Math.max(0, Math.round(ms / 1000));
  const m = Math.floor(totalS / 60);
  const s = totalS % 60;
  return `${m}:${String(s).padStart(2, '0')}`;
}

export function progressFraction(now: NowPlaying, progressMs: number): number {
  if (!now.duration_ms) return 0;
  return Math.min(1, Math.max(0, progressMs / now.duration_ms));
}

export function byWords(by: NowPlaying['by'] | NextItem['by']): string {
  return by.kind === 'set' ? "the host's set" : by.kind === 'host' ? 'added by the host'
    : `added by ${by.name}`;
}
