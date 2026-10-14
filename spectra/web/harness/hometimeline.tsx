/** Perf harness: mounts the REAL HomeTimeline (real rAF loop, real canvas
 * draw calls) against a MOCKED backend — no network, no real SPECTRA
 * process, zero live-room risk (same shape as harness/songstrip.tsx).
 * `window.__perf` exposes counters a CDP-driven measurement script reads:
 * rAF invocations (drawn fps), canvas clearRect calls (shape redraws),
 * and canvas width/height WRITES (backing-buffer resizes — should stay
 * flat once the window stops resizing, per the "resize only on real
 * change" guard). `window.__drag(...)` drives a synthetic window drag so
 * the measurement script can compare drag-time cadence against idle
 * cadence with no real pointer hardware involved. */
import '../src/styles/tokens.css';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import HomeTimeline from '../src/home/HomeTimeline';

const DURATION_MS = 200_000;
const START_MS = 60_000;

const SHAPE_META = {
  spotify_uri: 'spotify:track:perf', title: 'MR. OCTOBER', artist: 'Bad Bunny',
  duration_ms: DURATION_MS, sample_interval_ms: 200, music_marks: [],
  capture_complete: true, timestamp_offset_ms: 0, perception_trim_ms: 0,
  offset_verification: 'auto_verified',
};
const N = 1000;
const SHAPE_DATA = {
  timestamps_ms: Array.from({ length: N }, (_, i) => Math.round((i / N) * DURATION_MS)),
  rms_total: Array.from({ length: N }, (_, i) => 0.5 + 0.4 * Math.sin(i / 7)),
  rms_low: Array.from({ length: N }, (_, i) => 0.3 + 0.2 * Math.sin(i / 11)),
  rms_mid: Array.from({ length: N }, () => 0.2),
  rms_high: Array.from({ length: N }, (_, i) => 0.1 + 0.05 * Math.sin(i / 5)),
  avg_rms_1s: null,
};
const EVENTS = [
  { ms: 20000, kind: 'scene', rank: 1, rank_of: 3, source: 'planned' },
  { ms: 55000, kind: 'flare', rank: null, rank_of: null, source: 'analysed' },
  { ms: 90000, kind: 'charge', rank: null, rank_of: null, source: 'drop_sequence', num: 1 },
  { ms: 100000, kind: 'drop', rank: null, rank_of: null, source: 'drop_sequence', num: 1 },
  { ms: 150000, kind: 'low', rank: null, rank_of: null, source: 'show_cue' },
  { ms: 15000, kind: 'high', rank: null, rank_of: null, source: 'show_cue' },
];

window.fetch = (async (input: RequestInfo | URL) => {
  const url = String(input);
  const body = url.includes('/audio-shape/meta') ? SHAPE_META
    : url.includes('/audio-shape/data') ? SHAPE_DATA : {};
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } });
}) as typeof fetch;

class FakeSocket {
  onopen: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  readyState = 1;
  private t0 = performance.now();
  private timer: ReturnType<typeof setInterval>;
  constructor() {
    setTimeout(() => this.onopen?.(), 0);
    this.timer = setInterval(() => {
      const elapsedS = (performance.now() - this.t0) / 1000;
      const posMs = START_MS + elapsedS * 1000;
      this.onmessage?.({
        data: JSON.stringify({
          type: 'clock', show_clock_ms: posMs, position_ms: posMs,
          is_playing: true, server_ms: Date.now(),
        }),
      });
    }, 1000);
  }
  close() { clearInterval(this.timer); }
  send() {}
}
(window as unknown as { WebSocket: unknown }).WebSocket = FakeSocket;

let rafCount = 0;
const origRaf = window.requestAnimationFrame.bind(window);
window.requestAnimationFrame = (cb: FrameRequestCallback) => origRaf((t) => { rafCount += 1; cb(t); });

let clearRectCount = 0;
const origClearRect = CanvasRenderingContext2D.prototype.clearRect;
CanvasRenderingContext2D.prototype.clearRect = function (...a: Parameters<typeof origClearRect>) {
  clearRectCount += 1;
  return origClearRect.apply(this, a);
};

let resizeCount = 0;
const widthDesc = Object.getOwnPropertyDescriptor(HTMLCanvasElement.prototype, 'width')!;
Object.defineProperty(HTMLCanvasElement.prototype, 'width', {
  configurable: true,
  get() { return widthDesc.get!.call(this); },
  set(v) { resizeCount += 1; widthDesc.set!.call(this, v); },
});

(window as unknown as { __perf: unknown }).__perf = {
  get rafCount() { return rafCount; },
  get clearRectCount() { return clearRectCount; },
  get resizeCount() { return resizeCount; },
};

const root = createRoot(document.getElementById('root')!);
root.render(
  <QueryClientProvider client={new QueryClient()}>
    <MemoryRouter>
      <HomeTimeline
        uri="spotify:track:perf" title="MR. OCTOBER" artist="Bad Bunny"
        durationMs={DURATION_MS} events={EVENTS as never} showAudioShape
      />
    </MemoryRouter>
  </QueryClientProvider>,
);

// A synthetic window drag — real PointerEvents, dispatched at a fixed
// cadence, so the measurement script can compare drawn-fps during a drag
// against drawn-fps at idle with no real input hardware. Drags the
// window-overlay's centre handle `steps` times, `intervalMs` apart.
(window as unknown as { __drag: unknown }).__drag = (steps = 40, intervalMs = 16) => {
  const overlay = document.querySelector('.home-timeline-window') as HTMLElement | null;
  if (!overlay) return;
  let i = 0;
  let x = 100;
  overlay.dispatchEvent(new PointerEvent('pointerdown', {
    bubbles: true, cancelable: true, button: 0, buttons: 1, pointerId: 1, clientX: x,
  }));
  const id = setInterval(() => {
    i += 1;
    x += 5;
    window.dispatchEvent(new PointerEvent('pointermove', {
      bubbles: true, cancelable: true, button: 0, buttons: 1, pointerId: 1, clientX: x,
    }));
    if (i >= steps) {
      clearInterval(id);
      window.dispatchEvent(new PointerEvent('pointerup', {
        bubbles: true, cancelable: true, button: 0, buttons: 1, pointerId: 1, clientX: x,
      }));
    }
  }, intervalMs);
};
