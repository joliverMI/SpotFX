/** THE SYSTEM PLANE — plan §7's architecture table: "clock health ·
 * reconnect · calibrate". Deliberately small and dim (a diagnostic strip
 * in a corner, never the main thing a person across the room looks at).
 * Phase 1.1 has no feed to report on yet (that's 1.2) — it shows the
 * shell's own build id (so a stale TV can be told apart from a fresh one
 * by eye during the test evening) and a plain "not connected" state. */
import { TV_BUILD_ID } from './build';

export default function SystemPlane() {
  return (
    <div className="tv-system-plane" aria-hidden="true">
      <span>build {TV_BUILD_ID}</span>
      <span className="tv-system-dot" data-state="not-connected" />
    </div>
  );
}
