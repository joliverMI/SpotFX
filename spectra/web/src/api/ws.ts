/** Singleton WebSocket client — port of frontend/js/app.js (connectWS/onMessage).
 * Connects lazily on first subscription; reconnects after 3s. */

type Listener = (msg: Record<string, unknown>) => void;

const listeners = new Map<string, Set<Listener>>();
const stateListeners = new Set<(connected: boolean) => void>();
let ws: WebSocket | null = null;
let started = false;
let connected = false;

function connect() {
  ws = new WebSocket(`ws://${location.host}/ws`);
  ws.onopen = () => {
    connected = true;
    stateListeners.forEach((fn) => fn(true));
  };
  ws.onmessage = (e) => {
    try {
      const msg = JSON.parse(e.data as string);
      listeners.get(msg.type)?.forEach((fn) => fn(msg));
    } catch {
      /* ignore malformed */
    }
  };
  ws.onclose = () => {
    connected = false;
    stateListeners.forEach((fn) => fn(false));
    setTimeout(connect, 3000);
  };
  ws.onerror = () => ws?.close();
}

function ensureStarted() {
  if (!started) {
    started = true;
    connect();
  }
}

/** Subscribe to a message type; returns an unsubscribe fn (hook-friendly). */
export function onMessage(type: string, fn: Listener): () => void {
  ensureStarted();
  let set = listeners.get(type);
  if (!set) {
    set = new Set();
    listeners.set(type, set);
  }
  set.add(fn);
  return () => set!.delete(fn);
}

export function onConnectionChange(fn: (connected: boolean) => void): () => void {
  ensureStarted();
  stateListeners.add(fn);
  fn(connected);
  return () => stateListeners.delete(fn);
}

export const isConnected = () => connected;
