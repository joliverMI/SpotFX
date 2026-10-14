/** Perf harness: mounts the REAL SongStrip (real rAF loop, real SVG/
 * textContent writes) against a MOCKED backend — no network, no real
 * SPECTRA process, zero live-room risk (song-layout-plan drawn-fps
 * measurement, data/ui-layout-plan/report.md §4.2). `fetch` is stubbed to
 * serve canned `/engine/status` / `/upcoming` JSON; `WebSocket` is stubbed
 * to a fake socket that pushes a `{"type":"clock",...}` message once a
 * second with an advancing position — the SAME push shape
 * lib/showClock.ts listens for — so the strip animates exactly as it
 * would live between pushes. `window.__perf` exposes a few counters a
 * CDP-driven measurement script reads after letting it run. */
import '../src/styles/tokens.css';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import SongStrip from '../src/components/SongStrip';

const DURATION_MS = 189_258;
const START_MS = 20_000;

const STATUS = {
  bridge: {
    track: {
      uri: 'spotify:track:perf', title: 'MR. OCTOBER', artist: 'Bad Bunny',
      duration_ms: DURATION_MS, is_playing: true, position_ms: START_MS,
      show_clock_ms: START_MS,
    },
  },
};
const UPCOMING = {
  uri: 'spotify:track:perf', effective_mode: 'analysed', has_authored: false,
  events: [
    { ms: 30928, kind: 'flare', rank: 9, rank_of: 15, source: 'analysed' },
    { ms: 47821, kind: 'scene', rank: 7, rank_of: 15, source: 'planned' },
    { ms: 55089, kind: 'flare', rank: 12, rank_of: 15, source: 'analysed' },
    { ms: 61990, kind: 'drop', rank: null, rank_of: null, source: 'drop_sequence', num: 1 },
    { ms: 69021, kind: 'scene', rank: 15, rank_of: 15, source: 'planned' },
    { ms: 169726, kind: 'low', rank: null, rank_of: null, source: 'show_cue' },
    { ms: 20549, kind: 'high', rank: null, rank_of: null, source: 'show_cue' },
  ],
};

window.fetch = (async (input: RequestInfo | URL) => {
  const url = String(input);
  const body = url.includes('/engine/status') ? STATUS
    : url.includes('/upcoming') ? UPCOMING : {};
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
(window as unknown as { __perf: unknown }).__perf = {
  get rafCount() { return rafCount; },
};

createRoot(document.getElementById('root')!).render(
  <QueryClientProvider client={new QueryClient()}>
    <MemoryRouter><SongStrip /></MemoryRouter>
  </QueryClientProvider>,
);
