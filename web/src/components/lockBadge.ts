/** Sync-lock badge — the whole decision, as one pure function.
 *
 * WHY THIS IS ITS OWN MODULE: the badge used to be driven ONLY by the
 * `xcorr_monitor` websocket, which is the POST-LOCK drift monitor — it runs
 * only once a song hard-locks. With no monitor message and any stored offset
 * the badge printed "Lock idle", so a song still searching, a song that
 * finished at grade F, and a song genuinely idle after a good lock all read
 * identically. The Admiral's report, verbatim: when a song has not locked the
 * badge "should be failed or still trying" — not "Lock idle". The states are
 * now decided here, away from React, so `scripts/check_lock_badge_states.mjs`
 * can drive the real function over the whole table rather than a copy of it.
 *
 * THE ONE INVARIANT: `Lock idle` is reachable from EXACTLY ONE input — a
 * search that ENDED IN A HARD LOCK whose live monitor has since gone quiet.
 * A song still searching, one that finished without a lock, and one nobody
 * checked each have their own words. Never widen that.
 *
 * PRECEDENCE, in order, and each rung is there for a reason:
 *   1  a fresh monitor message — live evidence, the strongest thing we have
 *   2  searching   — the engine is looking right now
 *   3  unlocked    — the engine finished looking and found no lock
 *   4  locked      — it found one; the monitor has just gone quiet since
 *   5  no offset   — nothing stored to be in sync with (unchanged behaviour)
 *   6  skipped     — no sweep ran this play, and why
 *   7  unknown     — we have not heard yet; say so rather than guess
 */

/** A monitor message is live evidence for this long after it lands. */
export const LOCK_STALE_MS = 12_000;

export const MONITOR_LABEL: Record<string, string> = {
  ok: 'Locked',
  suspect: 'Suspect',
  recovering: 'Recovering',
};
export const MONITOR_COLOR: Record<string, string> = {
  ok: '#00ff88',
  suspect: '#ffb300',
  recovering: '#ff5252',
};

const NEUTRAL = '#888';
const SEARCHING_COLOR = '#4da3ff';
const FAILED_COLOR = '#ff5252';

/** Mirrors `services/lock_state.py`'s record, which arrives BOTH as a
 * `lock_state` websocket push and on every `state` broadcast. */
export interface LockStateRecord {
  uri?: string | null;
  phase?: string;
  windows_total?: number;
  windows_done?: number;
  offset_ms?: number | null;
  quality?: number | null;
  reason?: string | null;
  play_type?: string | null;
}

export interface LockBadge {
  label: string;
  color: string;
  title: string;
}

export interface LockBadgeInput {
  /** Newest `xcorr_monitor` message, or null if none has arrived. */
  monitor: { state: string; at: number } | null;
  nowMs: number;
  /** The lock record for the song playing now — see `lockForUri`. */
  lock: LockStateRecord | null;
  /** `timing.shape_offset_ms`; null/undefined means nothing is stored. */
  storedOffsetMs: number | null | undefined;
}

/** A record only counts for the song actually playing. The server already
 * filters its `state` copy this way; the pushed copy has to be filtered here,
 * so both paths land on one rule. */
export function lockForUri(
  rec: LockStateRecord | null | undefined,
  uri: string | null | undefined,
): LockStateRecord | null {
  if (!rec || !uri || rec.uri !== uri) return null;
  return rec;
}

/** Why no sweep ran, in words rather than a wire token. */
function skipReason(reason: string | null | undefined): string {
  switch (reason) {
    case 'no_shape':
      return 'this song has no complete audio shape to match against';
    case 'capture_in_progress':
      return 'an audio-shape capture was running, which the matcher stands clear of';
    case 'setlist_disabled':
      return 'this Set List has cross-correlation turned off, so the stored offset stands';
    case 'no_windows':
      return 'the song was already past every planned match window when it started';
    default:
      return 'no sweep ran for this song this play';
  }
}

function failReason(reason: string | null | undefined): string {
  if (reason === 'no_measurements') return ' — no window produced a usable measurement';
  return '';
}

function offsetPhrase(rec: LockStateRecord): string {
  if (rec.offset_ms == null) return '';
  const q = rec.quality == null ? '' : `, Q=${rec.quality.toFixed(2)}`;
  return ` Best it found: ${rec.offset_ms > 0 ? '+' : ''}${rec.offset_ms}ms${q}.`;
}

export function lockBadge(input: LockBadgeInput): LockBadge {
  const { monitor, nowMs, lock, storedOffsetMs } = input;

  // 1 — a live monitor message outranks everything: it is the matcher itself
  // reporting on the offset in use right now.
  if (monitor && nowMs - monitor.at < LOCK_STALE_MS) {
    return {
      label: MONITOR_LABEL[monitor.state] ?? monitor.state,
      color: MONITOR_COLOR[monitor.state] ?? NEUTRAL,
      title: 'Audio sync lock — the live-capture matcher is checking the current offset against what it hears.',
    };
  }

  const phase = lock?.phase;

  // 2 — still trying.
  if (lock && phase === 'searching') {
    const done = lock.windows_done ?? 0;
    const total = lock.windows_total ?? 0;
    const progress = total > 0 ? ` ${Math.min(done, total)}/${total}` : '';
    return {
      label: `Searching…${progress}`,
      color: SEARCHING_COLOR,
      title:
        `Audio sync lock — the matcher is still searching this song for an alignment.${
          total > 0 ? ` ${done} of ${total} planned windows measured.` : ''
        }${offsetPhrase(lock)}`,
    };
  }

  // 3 — it looked, and it did not find one. This is what used to read "idle".
  if (lock && phase === 'unlocked') {
    return {
      label: 'Lock failed',
      color: FAILED_COLOR,
      title:
        `Audio sync lock — the matcher finished searching this song without reaching a lock${failReason(
          lock.reason,
        )}. Triggers are firing against whatever offset was already stored.${offsetPhrase(lock)}`,
    };
  }

  // 4 — the ONLY idle: a search that ended in a hard lock, monitor now quiet.
  if (lock && phase === 'locked') {
    return {
      label: 'Lock idle',
      color: NEUTRAL,
      title:
        `Audio sync lock — this song locked and the matcher has stopped checking, so nothing is being reported right now.${offsetPhrase(
          lock,
        )}`,
    };
  }

  // 5 — nothing stored to be in sync with (unchanged).
  if (storedOffsetMs == null) {
    return {
      label: 'No lock',
      color: NEUTRAL,
      title: 'Audio sync lock — no offset is stored for this song, so triggers fire on Spotify position alone.',
    };
  }

  // 6 — nobody checked, and why. Not the same fact as "checked, and fine".
  if (lock && phase === 'skipped') {
    return {
      label: 'Not checked',
      color: NEUTRAL,
      title: `Audio sync lock — the stored offset is in use, unchecked this play: ${skipReason(lock.reason)}.`,
    };
  }

  // 7 — we have not heard yet. Say that rather than claim a lock we cannot see.
  return {
    label: 'Lock unknown',
    color: NEUTRAL,
    title:
      'Audio sync lock — an offset is stored, but nothing has reported on this song yet. It will resolve on the next poll.',
  };
}
