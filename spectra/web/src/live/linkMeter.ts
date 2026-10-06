/** The Live view's link meter: what THIS browser is getting over THIS link,
 * computed from the preview stream's own message headers
 * (spectra/services/preview_stream.py) — nothing to set up, no test to run.
 *
 *   fps      messages a second. The server sends one per tick, and only when
 *            something changed, so a still room reads low without the link
 *            being slow.
 *   delay    how old the picture is when it is drawn:
 *              half the server's measured round trip (the one-way trip)
 *            + how much later than the link's best this message came
 *            + how long the frame waited on the server for its tick
 *            + what smoothing holds back.
 *            The server's clock and this one need not agree: lateness is
 *            measured against the smallest (arrival - sent) seen recently,
 *            which cancels any fixed difference between the two clocks.
 *   kbit/s   bytes of stream messages received, before the browser undid the
 *            WebSocket's compression — so the link itself carries less.
 *
 * Fixed-size rings; nothing is allocated per message. */
import type { PreviewLinkStats } from '../api/devicePreviewWs';

const RING = 256;
const WINDOW_MS = 2000;
const BASELINE_MS = 10000;

export interface LinkReading {
  fps: number;
  delayMs: number | null;
  kbps: number;
  rateFps: number;
}

export class LinkMeter {
  private at = new Float64Array(RING);
  private bytes = new Float64Array(RING);
  private head = 0;
  private filled = 0;
  // Two alternating buckets give a rolling minimum without keeping history.
  private baseline = [Infinity, Infinity];
  private bucketAt = 0;
  private late = 0;
  private age = 0;
  private srtt = 0;
  private rate = 0;

  note(bytes: number, stats: PreviewLinkStats, maxAgeMs: number, at: number) {
    this.at[this.head] = at;
    this.bytes[this.head] = bytes;
    this.head = (this.head + 1) % RING;
    if (this.filled < RING) this.filled++;
    const offset = performance.timeOrigin + at - stats.sentMs;
    if (at - this.bucketAt > BASELINE_MS / 2) {
      this.baseline[1] = this.baseline[0];
      this.baseline[0] = Infinity;
      this.bucketAt = at;
    }
    if (offset < this.baseline[0]) this.baseline[0] = offset;
    const late = offset - Math.min(this.baseline[0], this.baseline[1]);
    this.late += (late - this.late) * 0.1;
    this.age += (maxAgeMs - this.age) * 0.1;
    this.srtt = stats.srttMs;
    this.rate = stats.rateFps;
  }

  read(now: number, holdMs: number, out: LinkReading): LinkReading {
    let count = 0;
    let total = 0;
    let oldest = now;
    for (let i = 0; i < this.filled; i++) {
      const t = this.at[i];
      if (now - t <= WINDOW_MS) {
        count++;
        total += this.bytes[i];
        if (t < oldest) oldest = t;
      }
    }
    // Until the window is full, divide by the time actually covered.
    const span = Math.max(500, Math.min(WINDOW_MS, now - oldest + 1000 / Math.max(this.rate, 1)));
    out.fps = count ? (count * 1000) / span : 0;
    out.kbps = count ? (total * 8) / span : 0;
    out.rateFps = this.rate;
    out.delayMs = count && this.srtt ? this.srtt / 2 + this.late + this.age + holdMs : null;
    return out;
  }

  reset() {
    this.filled = 0;
    this.head = 0;
    this.baseline = [Infinity, Infinity];
    this.late = 0;
    this.age = 0;
    this.srtt = 0;
  }
}
