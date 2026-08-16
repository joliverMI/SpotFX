/** Singleton WebSocket client for the device-preview strip
 * (/spectra/api/device-preview/ws) — same lazy-connect/reconnect shape as
 * api/ws.ts's spot-effects client, but a SEPARATE connection: pixel frames
 * are a different volume/cadence than the general event fan-out, and this
 * one carries the live "connected" truth the pause control's own honesty
 * depends on (services/device_preview.py's module docstring). Module-level
 * state, not component state, so the connection survives page navigation
 * — DevicePreviewStrip is mounted once in TopBarStrip.tsx, outside
 * <Routes>, but even if it weren't, this module would still hold one
 * connection for the whole tab's lifetime rather than one per mount.
 *
 * HIDDEN-TAB AUTO-PAUSE (OQ-7, decided 2026-08-15 —
 * docs/SPECTRA_SPEC.md, services/device_preview.py's docstring): this
 * socket IS the auto-pause signal. A hidden tab closes it deliberately;
 * the server treats a zero-viewer moment as "nobody's watching" and
 * drops its own live upstream connection for real (whichever source is
 * active — see DevicePreviewStatus.source in types.ts) — the same genuine
 * stop the sticky Pause button uses, never a display-only imitation. The
 * tab reopens it the instant it's visible again — no click needed. This
 * never calls pause()/resume(): those are his own sticky, persisted
 * choice, and an automatic pause must never look or persist like one he
 * has to remember to undo. `tabHiddenPause` is local knowledge — WE
 * closed this socket on purpose — so DevicePreviewStrip can show a
 * distinct "idle — tab hidden" state instead of the ordinary
 * "reconnecting…" (which means something different: the live upstream
 * connection is unexpectedly unreachable). */
import type { DevicePreviewFrame, DevicePreviewStatus } from '../types';

type FrameListener = (frame: DevicePreviewFrame) => void;
type StatusListener = (status: DevicePreviewStatus) => void;
type TabHiddenPauseListener = (paused: boolean) => void;

const frameListeners = new Set<FrameListener>();
const statusListeners = new Set<StatusListener>();
const tabHiddenPauseListeners = new Set<TabHiddenPauseListener>();
let lastStatus: DevicePreviewStatus | null = null;
let ws: WebSocket | null = null;
let started = false;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
// True from the moment WE close the socket because the tab went hidden,
// until a fresh status message confirms the reopened connection's real
// state — the window during which the badge must say "idle", not
// "paused" or "reconnecting…".
let tabHiddenPause = false;
// True only for the close WE initiate for a hidden tab — tells onclose
// apart a deliberate pause from a genuinely unexpected drop.
let intentionalClose = false;

function wsUrl(): string {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${proto}//${location.host}/spectra/api/device-preview/ws`;
}

function setTabHiddenPause(v: boolean) {
  if (tabHiddenPause !== v) {
    tabHiddenPause = v;
    tabHiddenPauseListeners.forEach((fn) => fn(tabHiddenPause));
  }
}

function connect() {
  ws = new WebSocket(wsUrl());
  ws.onmessage = (e) => {
    let msg: Record<string, unknown>;
    try {
      msg = JSON.parse(e.data as string);
    } catch {
      return;
    }
    if (msg.type === 'device_preview_frame') {
      frameListeners.forEach((fn) => fn(msg as unknown as DevicePreviewFrame));
    } else if (msg.type === 'device_preview_status') {
      lastStatus = msg as unknown as DevicePreviewStatus;
      statusListeners.forEach((fn) => fn(lastStatus!));
      // The reopened socket's first authoritative status has arrived —
      // hand display back to the ordinary paused/connected fields.
      setTabHiddenPause(false);
    }
  };
  ws.onclose = () => {
    const wasIntentional = intentionalClose;
    intentionalClose = false;
    ws = null;
    if (document.hidden) return; // still hidden — visibilitychange resumes it
    // Visible now: either a genuinely unexpected drop (gentle backoff, same
    // as before this feature existed), or the tail of our OWN hidden-tab
    // close racing a fast toggle back to visible (reconnect immediately —
    // "auto-resume without him touching anything" must not eat a 3s stall).
    if (wasIntentional) connect();
    else reconnectTimer = setTimeout(connect, 3000);
  };
  ws.onerror = () => ws?.close();
}

function ensureStarted() {
  if (!started) {
    started = true;
    document.addEventListener('visibilitychange', () => {
      if (document.hidden) {
        setTabHiddenPause(true);
        if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
        intentionalClose = true;
        ws?.close();
      } else if (ws === null || ws.readyState === WebSocket.CLOSED) {
        connect();
      }
    });
    // A tab can load already hidden (opened in the background) — honour
    // that from the first frame rather than connecting once and only
    // reacting from the next transition onward.
    if (document.hidden) setTabHiddenPause(true);
    else connect();
  }
}

export function onDevicePreviewFrame(fn: FrameListener): () => void {
  ensureStarted();
  frameListeners.add(fn);
  return () => frameListeners.delete(fn);
}

/** Fires immediately with the last-known status (if any) on subscribe, so
 * a component mounted after the connection opened doesn't wait for the
 * next status push to know paused/connected state. */
export function onDevicePreviewStatus(fn: StatusListener): () => void {
  ensureStarted();
  statusListeners.add(fn);
  if (lastStatus) fn(lastStatus);
  return () => statusListeners.delete(fn);
}

/** Fires immediately with the current tab-hidden-auto-pause state on
 * subscribe (see the module docstring) — distinct from, and never
 * written into, DevicePreviewStatus.paused. */
export function onDevicePreviewTabHiddenPause(fn: TabHiddenPauseListener): () => void {
  ensureStarted();
  tabHiddenPauseListeners.add(fn);
  fn(tabHiddenPause);
  return () => tabHiddenPauseListeners.delete(fn);
}

/** Decode a device-preview pixel payload (report §1, behaviour read from
 * LedFx-Frontend-v2's PixelGraphBase.tsx/hexColor.ts — reimplemented here,
 * not copied; that frontend is AGPL-3.0 and this repo is public).
 * Compressed mode (LedFX's default) is a base64 string of interleaved
 * r,g,b bytes; uncompressed mode is [[r...],[g...],[b...]] — SPECTRA never
 * changes LedFX's own transmission_mode config, so both shapes have to be
 * handled here. Also the wire shape `spectra/services/device_preview.py`
 * emits for its OWN in-process facade source (2026-08-16) — deliberately
 * matched to LedFX's uncompressed list form so this decoder needs no
 * source-aware branch; that backend encoding is independently written,
 * not derived from LedFX's own core.py (see that module's docstring). */
export function decodePixels(pixels: string | number[][]): [number, number, number][] {
  if (typeof pixels === 'string') {
    if (!pixels) return [];
    const bytes = Uint8Array.from(atob(pixels), (c) => c.charCodeAt(0));
    const out: [number, number, number][] = [];
    for (let i = 0; i + 2 < bytes.length; i += 3) {
      out.push([bytes[i], bytes[i + 1], bytes[i + 2]]);
    }
    return out;
  }
  const [rs, gs, bs] = pixels;
  if (!rs || !rs.length) return [];
  return rs.map((r, i) => [r, gs?.[i] ?? 0, bs?.[i] ?? 0]);
}

export function averageRgb(triples: [number, number, number][]): string {
  if (!triples.length) return 'rgb(40,40,40)';
  let r = 0, g = 0, b = 0;
  for (const [rr, gg, bb] of triples) { r += rr; g += gg; b += bb; }
  const n = triples.length;
  return `rgb(${Math.round(r / n)},${Math.round(g / n)},${Math.round(b / n)})`;
}
