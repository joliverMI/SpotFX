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
 * connection is unexpectedly unreachable).
 *
 * PROTOCOL 2 (2026-10-05, spectra/services/preview_stream.py is the binding
 * statement of the wire format). On open this client says hello; the server
 * then sends ONE binary message per tick instead of one JSON frame per
 * device, and this client ACKNOWLEDGES every message the moment it arrives.
 * Those acks are what pace the server: it stops when too many are
 * outstanding, so a slow link gets fewer, current frames, never a growing
 * backlog. Three things to keep true:
 *   - the ack is sent on RECEIPT, before any listener paints — a busy page
 *     then delays its own acks, which is exactly the signal the server needs;
 *   - a record's pixels are a VIEW into the message's own buffer (no copy);
 *     a listener that keeps one keeps that buffer alive, which is fine for
 *     "the last frame per device" and wrong for a history;
 *   - the LEVEL is the most any current consumer needs. The collapsed strip
 *     asks for "summary" (three bytes per device); only a view that draws
 *     pixels asks for "full".
 * A server that predates protocol 2 ignores the hello and keeps sending JSON
 * frames; those are decoded into the same PreviewFrame shape, so consumers
 * have one paint path. localStorage `spectra-device-preview-legacy` = '1'
 * skips the hello on purpose (the old format, for comparison). */
import type { DevicePreviewStatus } from '../types';

export type PreviewLevel = 'summary' | 'full';

/** One device's picture, from either wire format. `rgb` holds r,g,b per
 * REAL cell; `cellIndex[i]` is the position (row-major in rows x cols) of
 * cell i, or null when every cell of the rectangle is real. A summary frame
 * is one cell: the device's mean colour. */
export interface PreviewFrame {
  visId: string;
  kind: PreviewLevel;
  rows: number;
  cols: number;
  rgb: Uint8Array;
  cellIndex: Uint32Array | null;
  frameSeq: number;
  ageMs: number;
}

/** What the last message's header said about the link (protocol 2 only). */
export interface PreviewLinkStats {
  rateFps: number;
  srttMs: number;
  sentMs: number;
  seq: number;
}

interface DeviceLayout {
  visId: string;
  rows: number;
  cols: number;
  cellIndex: Uint32Array | null;
}

type FrameListener = (frame: PreviewFrame) => void;
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
let layouts: DeviceLayout[] = [];
let linkStats: PreviewLinkStats | null = null;
const levelRequests = new Map<string, PreviewLevel>();
let sentLevel: PreviewLevel | null = null;

const MAGIC = 0xd7;
const HEADER_BYTES = 20;
const RECORD_BYTES = 12;

function wantedLevel(): PreviewLevel {
  for (const level of levelRequests.values()) if (level === 'full') return 'full';
  return 'summary';
}

function legacyForced(): boolean {
  try {
    return localStorage.getItem('spectra-device-preview-legacy') === '1';
  } catch {
    return false;
  }
}

function sendLevel() {
  if (!ws || ws.readyState !== WebSocket.OPEN || sentLevel === null) return;
  const level = wantedLevel();
  if (level !== sentLevel) {
    sentLevel = level;
    ws.send(JSON.stringify({ type: 'subscribe', level }));
  }
}

function base64Bytes(text: string): Uint8Array {
  const bin = atob(text);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

function readLayout(devices: Array<Record<string, unknown>>) {
  layouts = [];
  for (const d of devices) {
    let cellIndex: Uint32Array | null = null;
    if (typeof d.mask === 'string') {
      const bits = base64Bytes(d.mask);
      cellIndex = new Uint32Array(Number(d.cells));
      let n = 0;
      const total = Number(d.rows) * Number(d.cols);
      for (let i = 0; i < total && n < cellIndex.length; i++) {
        if (bits[i >> 3] & (0x80 >> (i & 7))) cellIndex[n++] = i;
      }
    }
    layouts[Number(d.index)] = {
      visId: String(d.vis_id), rows: Number(d.rows), cols: Number(d.cols), cellIndex,
    };
  }
}

function readBinary(buffer: ArrayBuffer, socket: WebSocket) {
  if (buffer.byteLength < HEADER_BYTES) return;
  const view = new DataView(buffer);
  if (view.getUint8(0) !== MAGIC) return;
  const count = view.getUint8(2);
  const seq = view.getUint32(4, true);
  // Ack FIRST: the server paces itself on this.
  if (socket.readyState === WebSocket.OPEN) socket.send(`{"type":"ack","seq":${seq}}`);
  linkStats = {
    rateFps: view.getUint8(3), seq, sentMs: view.getFloat64(8, true),
    srttMs: view.getUint16(16, true),
  };
  let offset = HEADER_BYTES;
  for (let i = 0; i < count && offset + RECORD_BYTES <= buffer.byteLength; i++) {
    const layout = layouts[view.getUint8(offset)];
    const kind: PreviewLevel = view.getUint8(offset + 1) === 1 ? 'full' : 'summary';
    const ageMs = view.getUint16(offset + 2, true);
    const frameSeq = view.getUint32(offset + 4, true);
    const length = view.getUint32(offset + 8, true);
    offset += RECORD_BYTES;
    if (layout && offset + length <= buffer.byteLength) {
      const frame: PreviewFrame = {
        visId: layout.visId, kind, rows: layout.rows, cols: layout.cols,
        rgb: new Uint8Array(buffer, offset, length),
        cellIndex: kind === 'full' ? layout.cellIndex : null, frameSeq, ageMs,
      };
      frameListeners.forEach((fn) => fn(frame));
    }
    offset += length;
  }
}

/** The old JSON frame (and LedFX's own two transmission modes) as a
 * PreviewFrame: base64 of interleaved r,g,b, or [[r...],[g...],[b...]]. */
function legacyFrame(msg: Record<string, unknown>): PreviewFrame | null {
  const pixels = msg.pixels as string | number[][] | undefined;
  const shape = (msg.shape as [number, number] | undefined) ?? [1, 1];
  let rgb: Uint8Array;
  if (typeof pixels === 'string') {
    rgb = base64Bytes(pixels);
  } else if (Array.isArray(pixels) && pixels[0]) {
    const [rs, gs, bs] = pixels;
    rgb = new Uint8Array(rs.length * 3);
    for (let i = 0; i < rs.length; i++) {
      rgb[i * 3] = rs[i]; rgb[i * 3 + 1] = gs?.[i] ?? 0; rgb[i * 3 + 2] = bs?.[i] ?? 0;
    }
  } else {
    return null;
  }
  return {
    visId: String(msg.vis_id), kind: 'full', rows: shape[0], cols: shape[1], rgb,
    cellIndex: null, frameSeq: 0, ageMs: 0,
  };
}

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
  const socket = new WebSocket(wsUrl());
  ws = socket;
  socket.binaryType = 'arraybuffer';
  layouts = [];
  linkStats = null;
  sentLevel = null;
  socket.onopen = () => {
    if (legacyForced()) return;
    sentLevel = wantedLevel();
    socket.send(JSON.stringify({ type: 'hello', protocol: 2, level: sentLevel }));
  };
  ws.onmessage = (e) => {
    if (typeof e.data !== 'string') {
      readBinary(e.data as ArrayBuffer, socket);
      return;
    }
    let msg: Record<string, unknown>;
    try {
      msg = JSON.parse(e.data);
    } catch {
      return;
    }
    if (msg.type === 'device_preview_layout') {
      readLayout(msg.devices as Array<Record<string, unknown>>);
    } else if (msg.type === 'device_preview_frame') {
      const frame = legacyFrame(msg);
      if (frame) frameListeners.forEach((fn) => fn(frame));
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

/** Say what a consumer needs: 'full' while it draws pixels, 'summary' (or
 * null, on unmount) otherwise. The socket carries the most any consumer
 * asked for. */
export function setDevicePreviewLevel(consumer: string, level: PreviewLevel | null) {
  if (level === null) levelRequests.delete(consumer);
  else levelRequests.set(consumer, level);
  sendLevel();
}

/** Rate, round trip and send time from the newest message header, or null
 * before the first protocol-2 message. */
export function devicePreviewLinkStats(): PreviewLinkStats | null {
  return linkStats;
}

/** Mean colour of a frame's cells, as a CSS colour. */
export function frameColor(frame: PreviewFrame): string {
  const { rgb } = frame;
  const n = Math.floor(rgb.length / 3);
  if (!n) return 'rgb(40,40,40)';
  let r = 0, g = 0, b = 0;
  for (let i = 0; i < n * 3; i += 3) { r += rgb[i]; g += rgb[i + 1]; b += rgb[i + 2]; }
  return `rgb(${Math.round(r / n)},${Math.round(g / n)},${Math.round(b / n)})`;
}
