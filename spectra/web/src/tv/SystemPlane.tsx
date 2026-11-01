/** THE SYSTEM PLANE — plan §7's architecture table: "clock health ·
 * reconnect · calibrate". Deliberately small and dim (a diagnostic strip
 * in a corner, never the main thing a person across the room looks at).
 * Now wired to the real feed (PR 1.2): the dot is green once connected,
 * and the clock-offset readout is the one visible proof, at the TV
 * itself, that the NTP ping/pong (tv_feed.py/clock.ts) is actually
 * working — useful during the phase-0/1.2 test evening without needing
 * to open devtools on a TV that may not have any. */
import { TV_BUILD_ID } from './build';
import { useFeed } from './useFeed';

export default function SystemPlane() {
  const feed = useFeed();
  const offset = feed.offsetMs;
  return (
    <div className="tv-system-plane" aria-hidden="true">
      <span>build {TV_BUILD_ID}</span>
      <span className="tv-system-dot" data-state={feed.connected ? 'connected' : 'not-connected'} />
      {offset !== null && <span>clock {offset >= 0 ? '+' : ''}{offset.toFixed(0)}ms</span>}
    </div>
  );
}
