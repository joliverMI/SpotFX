/** THE TV FEED CLIENT (data/tv-display-plan/plan.html PR 1.2) — the one
 * WebSocket (`/spectra/api/tv/ws`, absolute: this app is always served
 * under /spectra, matching vite.tv.config.ts's own `base`) the TV app
 * talks to. `spectra/services/tv_feed.py`'s module docstring is the wire
 * protocol's binding statement; this is the client half.
 *
 * Reconnects with a fixed backoff on close — a TV left running overnight
 * must never need a human to reload it after a transient drop. The
 * build-id reload check runs on every `config` message (not just the
 * first), so a TV deployed mid-session still catches up the moment the
 * server reports a newer build. */
import { shouldReload, TV_BUILD_ID } from './build';
import { ClockAnchor, NtpClock } from './clock';
import { isJukeboxView, JukeboxView } from './jukeboxTypes';

export type Layout = 'party' | 'attract' | 'sleep' | 'calibrate' | 'lost';

export interface FeedState {
  connected: boolean;
  layout: Layout | null;
  clock: ClockAnchor | null;
  jukebox: JukeboxView | null;
  /** The client's own clock (nowMs()) at the moment `jukebox` last
   * changed — the Party screen (PR 1.4) interpolates `now.progress_ms`
   * forward from here between ~1 Hz relay pushes, the same shape the
   * show clock already uses for the identical reason. */
  jukeboxReceivedAtMs: number | null;
  offsetMs: number | null;
  /** nowMs() at the moment the socket most recently went DOWN, or null
   * while connected — the lost-connection screen (PR 1.5) reads this to
   * decide "quiet blip" (<5s) vs "reconnecting" overlay (5-60s) vs black
   * (>=60s). Cleared the instant `onopen` fires again. */
  disconnectedAtMs: number | null;
}

type Listener = (state: FeedState) => void;

const PING_INTERVAL_MS = 2000;
const RECONNECT_MS = 2000;
const SCREEN_ID_KEY = 'spectra-tv-screen-id';

/** `performance.now()` is relative to page-navigation start, not the
 * wall clock; `tv_feed.py`'s own timestamps are `time.time() * 1000.0`
 * (epoch ms) — mixing the two makes `NtpClock`'s offset meaningless (it
 * reads as the page's own age, not a real clock skew). `performance.
 * timeOrigin` is the epoch-ms moment `performance.now()` counts from, so
 * adding it back gives a monotonic-enough clock already on the server's
 * own epoch-ms scale — the "fixed origin" `clock.ts`'s own docstring
 * anticipates callers needing. */
export function nowMs(): number {
  return performance.timeOrigin + performance.now();
}

function screenId(): string {
  let id = '';
  try {
    id = window.localStorage.getItem(SCREEN_ID_KEY) || '';
  } catch {
    /* localStorage can throw in some embedded/kiosk contexts */
  }
  if (!id) {
    id = 'tv-' + Math.random().toString(16).slice(2);
    try {
      window.localStorage.setItem(SCREEN_ID_KEY, id);
    } catch {
      /* best effort only — a fresh id every reload is still correct */
    }
  }
  return id;
}

export class TvFeed {
  private ws: WebSocket | null = null;
  private ntp = new NtpClock();
  private pingTimer: ReturnType<typeof setInterval> | undefined;
  private reconnectTimer: ReturnType<typeof setTimeout> | undefined;
  private state: FeedState = {
    connected: false, layout: null, clock: null, jukebox: null,
    jukeboxReceivedAtMs: null, offsetMs: null, disconnectedAtMs: null,
  };
  private listeners = new Set<Listener>();
  private started = false;

  start(): void {
    if (this.started) return;
    this.started = true;
    this.connect();
  }

  subscribe(fn: Listener): () => void {
    this.listeners.add(fn);
    fn(this.state);
    return () => {
      this.listeners.delete(fn);
    };
  }

  private setState(patch: Partial<FeedState>): void {
    this.state = { ...this.state, ...patch };
    this.listeners.forEach((fn) => fn(this.state));
  }

  private connect(): void {
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(`${proto}//${window.location.host}/spectra/api/tv/ws`);
    this.ws = ws;
    ws.onopen = () => {
      ws.send(JSON.stringify({
        type: 'hello',
        screen_id: screenId(),
        build_id: TV_BUILD_ID,
        width: window.innerWidth,
        height: window.innerHeight,
        webgl2: !!document.createElement('canvas').getContext('webgl2'),
      }));
      this.setState({ connected: true, disconnectedAtMs: null });
      this.pingTimer = setInterval(() => this.sendPing(), PING_INTERVAL_MS);
      this.sendPing();
    };
    ws.onmessage = (ev) => this.handleMessage(String(ev.data));
    ws.onclose = () => {
      this.setState({ connected: false, disconnectedAtMs: this.state.disconnectedAtMs ?? nowMs() });
      if (this.pingTimer) clearInterval(this.pingTimer);
      this.reconnectTimer = setTimeout(() => this.connect(), RECONNECT_MS);
    };
    ws.onerror = () => ws.close();
  }

  private sendPing(): void {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
    this.ws.send(JSON.stringify({ type: 'ping', t: nowMs() }));
  }

  private handleMessage(raw: string): void {
    let msg: Record<string, unknown>;
    try {
      msg = JSON.parse(raw) as Record<string, unknown>;
    } catch {
      return;
    }
    switch (msg.type) {
      case 'config': {
        if (shouldReload((msg.build_id as string | null) ?? null)) {
          window.location.reload();
          return;
        }
        this.setState({ layout: (msg.layout as Layout) ?? this.state.layout });
        break;
      }
      case 'layout':
        this.setState({ layout: (msg.layout as Layout) ?? this.state.layout });
        break;
      case 'pong': {
        const clientRecvMs = nowMs();
        this.ntp.record(
          msg.client_t as number, msg.server_recv_ms as number,
          msg.server_send_ms as number, clientRecvMs,
        );
        this.setState({ offsetMs: this.ntp.offsetMs() });
        break;
      }
      case 'clock':
        this.setState({
          clock: {
            showClockMs: (msg.show_clock_ms as number | null) ?? null,
            serverMsAtReceipt: msg.server_ms as number,
            isPlaying: !!msg.is_playing,
          },
        });
        break;
      case 'jukebox':
        if (isJukeboxView(msg)) {
          this.setState({ jukebox: msg, jukeboxReceivedAtMs: nowMs() });
        }
        break;
      default:
        break;
    }
  }

  stop(): void {
    this.started = false;
    if (this.pingTimer) clearInterval(this.pingTimer);
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.ws?.close();
  }
}

export const feed = new TvFeed();
