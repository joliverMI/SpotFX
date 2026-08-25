/** TESTING IN PROGRESS — the loud, full-width top bar (his ask,
 * 2026-08-24, his THIRD time asking: "Make it loud when it's being tested
 * and just add a whole top bar it says testing in progress", after "Are my
 * lights being tested on?" and "weve been thru this befkre").
 *
 * Mounted FIRST in App.tsx, above NavBar — genuinely the top of every
 * route, not a badge and not a tint. Three things it says, in this order,
 * because that is the order he asks them in:
 *
 *   IS SOMEONE TESTING?   GET /test-session (spectra/services/
 *     test_session.py) — a server-side fold of the app's own test paths
 *     (a preview holding the room, a flare preview driving lights, a
 *     colour-set preview painting it) PLUS any declared take. The fold
 *     needs zero agent discipline: if a path holds his room, this lights.
 *
 *   WHO, AND SINCE WHEN?  The declared record's actor/reason/since_ms,
 *     rendered as his own local wall clock plus an elapsed duration.
 *
 *   IS IT ACTUALLY PAINTING?  GET /liveness. THE WHOLE REASON THIS
 *     MATTERS: an owner indicator showed green right through an outage he
 *     sat in. Owning the room and painting it are different facts, so the
 *     bar states which — "driving your lights (frames flowing)" vs
 *     "holding the room but NOT painting — that's a fault, not a test".
 *
 * DEFAULT TO SHOWING. The bar hides on exactly one answer: a confirmed
 * "no". An unreachable backend, an unreadable store, a probe that raised —
 * all render the distinct UNKNOWN form ("CAN'T CONFIRM..."), because a
 * silent bar during an outage is precisely the failure being fixed.
 * Transient poll blips are debounced (FAIL_STREAK_TO_SHOW consecutive
 * failures) so a single dropped request can't flicker it up and down. */
import { useEffect, useRef, useState } from 'react';
import HelpLink from '../help/HelpLink';
import { useLiveness, useTestSession } from '../queries';
import type { Liveness, TestSessionStatus } from '../types';

/** Two consecutive failed polls before we call the backend unreachable —
 * one dropped request on a phone over Tailscale is normal and must not
 * flash a warning bar at him. Two is ~6s at the 3s poll. */
export const FAIL_STREAK_TO_SHOW = 2;

/** His local wall clock, "since HH:MM" — the format he reads a room in. */
export function formatSince(sinceMs: number): string {
  const d = new Date(sinceMs);
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

/** Elapsed, only once it is worth saying (>1min) — under a minute the
 * clock time alone is the clearer statement. */
export function formatElapsed(sinceMs: number, nowMs: number): string | null {
  const secs = Math.floor((nowMs - sinceMs) / 1000);
  if (secs < 60) return null;
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m`;
  const hrs = Math.floor(mins / 60);
  return `${hrs}h ${mins % 60}m`;
}

/** The painting line — the owned-vs-painting distinction, in his words.
 * Exported so the DOM-free check script can drive the real formula. */
export function paintingLine(live: Liveness | null | undefined): string {
  if (!live) return 'can\'t read whether your lights are being painted';
  if (live.state === 'switching') return 'the room is changing hands right now';
  if (live.owner !== 'spectra') {
    if (live.owner === 'released') {
      return 'your room is RELEASED — nothing is driving your lights';
    }
    return `spot-effects owns your lights right now (SPECTRA is ${live.state})`;
  }
  if (live.state !== 'live') {
    return 'SPECTRA holds the room but her live stack is DOWN — that\'s a fault, not a test';
  }
  const gaps = Object.keys(live.activation_gaps ?? {}).length;
  const vals = Object.values(live.virtuals ?? {});
  const active = vals.filter((v) => v.active);
  const stale = active.filter((v) => !v.fresh);
  if (active.length === 0) {
    return 'holding the room but NOT painting — that\'s a fault, not a test';
  }
  if (stale.length > 0) {
    return `holding the room but ${stale.length} of ${active.length} light(s) STOPPED painting — that's a fault, not a test`;
  }
  if (gaps > 0) {
    return `driving ${active.length} light(s), but ${gaps} never came up — partly dark`;
  }
  return `driving your lights (${active.length} painting, frames flowing)`;
}

/** The one-line "who" — a declared take names itself; an auto-detected
 * source says what is holding the room instead of inventing a name. */
export function whoLine(st: TestSessionStatus): string {
  if (st.declared) return `${st.declared.actor} — ${st.declared.reason}`;
  const auto = st.sources.filter((s) => s.kind === 'auto');
  if (auto.length === 0) return 'someone (undeclared)';
  const first = auto[0];
  const extra = auto.length > 1 ? ` +${auto.length - 1} more` : '';
  return `${first.label}${first.detail ? ` (${first.detail})` : ''}${extra}`;
}

export default function TestingBar() {
  const { data: session, isError: sessionError } = useTestSession();
  const { data: liveness } = useLiveness();

  // Consecutive-failure debounce. A ref (not state) because updating it
  // must never itself trigger a render loop; the render reads it through
  // the `unreachable` state below, flipped only when the streak crosses.
  const failStreak = useRef(0);
  const [unreachable, setUnreachable] = useState(false);
  useEffect(() => {
    if (sessionError) {
      failStreak.current += 1;
      if (failStreak.current >= FAIL_STREAK_TO_SHOW) setUnreachable(true);
    } else if (session) {
      failStreak.current = 0;
      setUnreachable(false);
    }
  }, [sessionError, session]);

  // A ticking clock so the elapsed duration stays honest between polls.
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 10_000);
    return () => window.clearInterval(id);
  }, []);

  // The ONLY hiding condition: a confirmed "no" from a reachable backend.
  if (!unreachable && session?.testing === 'no') return null;
  // First load, nothing known yet and nothing failed yet — stay quiet
  // rather than flashing UNKNOWN on every page load.
  if (!unreachable && !session) return null;

  const unknown = unreachable || session?.testing === 'unknown';

  if (unknown) {
    return (
      <div className="testing-bar testing-bar-unknown" role="status" aria-live="polite">
        <div className="testing-bar-title">⚠ CAN'T CONFIRM</div>
        <div className="testing-bar-detail">
          <span className="testing-bar-headline">
            CAN'T CONFIRM whether your room is under test right now
          </span>
          <span className="testing-bar-sub">
            {unreachable
              ? 'SPECTRA is not answering — assume your lights may be in use'
              : 'a status source could not be read — assume your lights may be in use'}
          </span>
        </div>
        <HelpLink topic="testing-bar" title="What this bar means" />
      </div>
    );
  }

  const st = session as TestSessionStatus;
  const since = st.since_ms;
  const elapsed = since != null ? formatElapsed(since, now) : null;

  return (
    <div className="testing-bar testing-bar-yes" role="status" aria-live="polite">
      <div className="testing-bar-title">TESTING IN PROGRESS</div>
      <div className="testing-bar-detail">
        <span className="testing-bar-headline">
          {whoLine(st)}
          {since != null && (
            <> — since {formatSince(since)}{elapsed ? ` (${elapsed})` : ''}</>
          )}
        </span>
        <span className="testing-bar-sub">{paintingLine(liveness)}</span>
      </div>
      <HelpLink topic="testing-bar" title="What this bar means" />
    </div>
  );
}
