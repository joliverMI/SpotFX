/** THE ONE SHOW CLOCK (song-layout-plan, data/ui-layout-plan/report.md
 * §4.1/§7): every lane that draws a playhead — the global song timeline,
 * Home's editable copy, the Timeline page's own strips, the audio-shape
 * canvas — reads the SAME number: `show_clock_ms`, the exact moment the
 * trigger poll fires against (`spectra/services/engine.py::
 * current_show_clock_ms`). This closes the pre-existing three-playhead
 * mismatch (raw Spotify progress on the Timeline strips vs
 * position − audio_latency_ms + stored timestamp_offset_ms on the
 * audio-shape canvas vs the engine's own fire clock).
 *
 * Module-level singleton, the `spectraWs.ts`/`useLivePosition.ts` shape:
 * the freshest anchor — the 1 Hz WS "clock" push when it has arrived, the
 * 3 s GET /api/engine/status poll's `bridge.track.show_clock_ms` as the
 * backstop before the first push lands or after a dropped connection —
 * is interpolated with `performance.now()`. No React state: a per-frame
 * caller (a rAF loop) must read `getShowClockMs()` directly, never
 * subscribe a component to it, or every lane would re-render every
 * frame. `onShowClockChange` exists only for the rare caller that needs a
 * coarse re-render (e.g. a 4 Hz text readout), not the hot path.
 *
 * Honest accuracy note (report §4.1): tenths are displayed, but Spotify's
 * own position report jitters by a few hundred ms — this keeps drift
 * bounded to one WS push interval, never claims ±0.1 s accuracy. */
import { onSpectraMessage } from '../api/spectraWs';

interface Anchor {
  showClockMs: number | null;
  positionMs: number | null;
  isPlaying: boolean;
  /** performance.now() at the moment this anchor was taken. */
  receivedAt: number;
}

let anchor: Anchor | null = null;
let started = false;
const listeners = new Set<() => void>();

function setAnchor(next: Anchor) {
  anchor = next;
  listeners.forEach((fn) => fn());
}

function ensureStarted() {
  if (started) return;
  started = true;
  onSpectraMessage((msg) => {
    if (msg.type !== 'clock') return;
    setAnchor({
      showClockMs: (msg.show_clock_ms as number | null) ?? null,
      positionMs: (msg.position_ms as number | null) ?? null,
      isPlaying: !!msg.is_playing,
      receivedAt: performance.now(),
    });
  });
}

/** The 3 s engine-status poll's backstop (report §4.1: "the poll stays as
 * the backstop"). Call from wherever useEngineStatus() already resolves —
 * never a second poll of its own. A WS push that arrived more recently
 * than this poll always wins (the push is the fresher source); this only
 * ever advances the anchor when the poll is the newer one, e.g. before
 * the first push lands. */
export function seedShowClockFromStatus(track: {
  show_clock_ms: number | null; position_ms: number | null; is_playing: boolean | null;
} | null | undefined): void {
  ensureStarted();
  const now = performance.now();
  if (anchor && now - anchor.receivedAt < 2_500) return; // a push is fresher
  setAnchor({
    showClockMs: track?.show_clock_ms ?? null,
    positionMs: track?.position_ms ?? null,
    isPlaying: !!track?.is_playing,
    receivedAt: now,
  });
}

/** The show clock right now, interpolated from the freshest anchor. null
 * when no anchor has ever arrived, or the anchor itself carries no clock
 * (no track / bridge down) — never invented. Read this every frame from
 * a rAF loop; it is a plain function call, not a hook. */
export function getShowClockMs(): number | null {
  ensureStarted();
  if (!anchor || anchor.showClockMs == null) return anchor?.showClockMs ?? null;
  if (!anchor.isPlaying) return anchor.showClockMs;
  return anchor.showClockMs + (performance.now() - anchor.receivedAt);
}

/** The raw (non-show-clock) position, same shape, for a caller that wants
 * Spotify's own progress rather than the fire clock (e.g. "2:07 / 3:09",
 * which is about the song, not when the lights fire). */
export function getPositionMs(): number | null {
  ensureStarted();
  if (!anchor || anchor.positionMs == null) return anchor?.positionMs ?? null;
  if (!anchor.isPlaying) return anchor.positionMs;
  return anchor.positionMs + (performance.now() - anchor.receivedAt);
}

export function isShowPlaying(): boolean {
  ensureStarted();
  return !!anchor?.isPlaying;
}

/** Coarse change notification — NOT per frame. Use for a text readout
 * that only needs to repaint a few times a second, never for a canvas or
 * SVG playhead (those must poll getShowClockMs() from their own rAF). */
export function onShowClockChange(fn: () => void): () => void {
  ensureStarted();
  listeners.add(fn);
  return () => listeners.delete(fn);
}
