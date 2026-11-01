/** THE TV's OWN NTP-STYLE CLOCK (data/tv-display-plan/plan.html PR 1.2,
 * §7.1/§5.1: "ping/pong: client time -> server receive and send times …
 * NTP-style pings every 2 s; keep the fastest of the last 8"). Pure — no
 * network, no timers — so scripts/check_tv_clock.mjs can drive it with
 * synthetic timestamps; spectra/services/tv_feed.py's module docstring
 * has the server-side half of why this formula survives a server stall.
 *
 * `offset_ms` below is (server_clock - client_clock): add it to a
 * client-side `performance.now()`-style timestamp to read it on the
 * server's clock, which is what the show clock interpolator needs — the
 * TV draws for "now" on the SAME clock the lights fire against, never its
 * own. */
export interface PingSample {
  rttMs: number;
  offsetMs: number;
}

const MAX_SAMPLES = 8;

export class NtpClock {
  private samples: PingSample[] = [];

  /** `clientSendMs`/`clientRecvMs` are the TV's own clock (e.g.
   * `performance.now()` plus some fixed origin — any monotonic-enough
   * source the caller is consistent about); `serverRecvMs`/`serverSendMs`
   * come straight off the server's `pong` message. */
  record(clientSendMs: number, serverRecvMs: number, serverSendMs: number, clientRecvMs: number): void {
    const rttMs = Math.max(0, (clientRecvMs - clientSendMs) - (serverSendMs - serverRecvMs));
    const offsetMs = ((serverRecvMs - clientSendMs) + (serverSendMs - clientRecvMs)) / 2;
    this.samples.push({ rttMs, offsetMs });
    if (this.samples.length > MAX_SAMPLES) this.samples.shift();
  }

  /** The fastest (lowest-RTT) sample's offset — the plan's own rule — or
   * `null` before the first pong lands. */
  offsetMs(): number | null {
    if (this.samples.length === 0) return null;
    return this.samples.reduce((best, s) => (s.rttMs < best.rttMs ? s : best)).offsetMs;
  }

  bestRttMs(): number | null {
    if (this.samples.length === 0) return null;
    return Math.min(...this.samples.map((s) => s.rttMs));
  }

  sampleCount(): number {
    return this.samples.length;
  }
}

/** The show clock an incoming `clock` message describes, interpolated to
 * "now" on the CLIENT's own clock via the NTP offset — plan §7.1: "the TV
 * never times anything by when a message arrives" (SPECTRA's event loop
 * can stall, so a push can be late without the clock itself jumping).
 * `showClockMs`/`isPlaying` mirror the server's own fields; `null` show
 * clock (no track) is passed through untouched — nothing is invented. */
export interface ClockAnchor {
  showClockMs: number | null;
  serverMsAtReceipt: number;
  isPlaying: boolean;
}

export function interpolateShowClockMs(anchor: ClockAnchor, nowServerMs: number): number | null {
  if (anchor.showClockMs === null || !anchor.isPlaying) return anchor.showClockMs;
  return anchor.showClockMs + (nowServerMs - anchor.serverMsAtReceipt);
}
