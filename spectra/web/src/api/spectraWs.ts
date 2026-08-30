/** Singleton WebSocket client for SPECTRA's own engine fan-out
 * (/spectra/api/ws) — the channel spectra/services/ws.py's ws_manager
 * broadcasts on. Same lazy-connect/reconnect shape as api/ws.ts's
 * spot-effects client and api/devicePreviewWs.ts, and a SEPARATE
 * connection from both: this one carries SPECTRA-process events
 * (drift_leg / surge / sequencer_pick / ambient_status), not spot-effects'
 * event stream and not pixel frames.
 *
 * Why it exists at all (2026-08-30): the room bar's Ambient button has to
 * say "Turning on…" within a second of a press — the phase contract's own
 * requirement (spectra/services/ambient_music_gate.py). The 3s
 * engine-status poll cannot promise that, so the gate PUSHES its status at
 * every transition start/end/cancel and this client feeds it straight into
 * the same react-query cache entry the poll writes, so every reader of
 * useEngineStatus() sees the new phase immediately with no second source
 * of truth to keep in sync. The poll stays as the backstop.
 *
 * Module-level state, not component state, so one connection serves the
 * whole tab regardless of which routes are mounted. */

type Listener = (msg: Record<string, unknown>) => void;

const listeners = new Set<Listener>();
let ws: WebSocket | null = null;
let started = false;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

function url(): string {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${proto}//${location.host}/spectra/api/ws`;
}

function connect() {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;
  try {
    ws = new WebSocket(url());
  } catch {
    scheduleReconnect();
    return;
  }
  ws.onmessage = (e) => {
    let msg: Record<string, unknown>;
    try {
      msg = JSON.parse(e.data as string);
    } catch {
      return;
    }
    listeners.forEach((fn) => fn(msg));
  };
  ws.onclose = () => {
    ws = null;
    scheduleReconnect();
  };
  ws.onerror = () => ws?.close();
}

function scheduleReconnect() {
  if (!started || reconnectTimer) return;
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    connect();
  }, 2000);
}

/** Subscribe to every SPECTRA event message. Returns an unsubscribe. The
 * socket opens on the first subscriber and is deliberately never closed
 * again — reconnects are cheap and a dropped subscription mid-transition
 * would be exactly when the phase matters most. */
export function onSpectraMessage(fn: Listener): () => void {
  listeners.add(fn);
  if (!started) {
    started = true;
    connect();
  }
  return () => listeners.delete(fn);
}
