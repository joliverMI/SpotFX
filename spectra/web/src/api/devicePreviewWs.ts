/** Singleton WebSocket client for the device-preview strip
 * (/spectra/api/device-preview/ws) — same lazy-connect/reconnect shape as
 * api/ws.ts's spot-effects client, but a SEPARATE connection: pixel frames
 * are a different volume/cadence than the general event fan-out, and this
 * one carries the live "connected" truth the pause control's own honesty
 * depends on (services/device_preview.py's module docstring). Module-level
 * state, not component state, so the connection survives page navigation
 * — DevicePreviewStrip is mounted once in TopBarStrip.tsx, outside
 * <Routes>, but even if it weren't, this module would still hold one
 * connection for the whole tab's lifetime rather than one per mount. */
import type { DevicePreviewFrame, DevicePreviewStatus } from '../types';

type FrameListener = (frame: DevicePreviewFrame) => void;
type StatusListener = (status: DevicePreviewStatus) => void;

const frameListeners = new Set<FrameListener>();
const statusListeners = new Set<StatusListener>();
let lastStatus: DevicePreviewStatus | null = null;
let ws: WebSocket | null = null;
let started = false;

function wsUrl(): string {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${proto}//${location.host}/spectra/api/device-preview/ws`;
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
    }
  };
  ws.onclose = () => {
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

/** Decode LedFX's own VisualisationUpdateEvent pixel payload (report §1,
 * behaviour read from LedFx-Frontend-v2's PixelGraphBase.tsx/hexColor.ts —
 * reimplemented here, not copied; that frontend is AGPL-3.0 and this repo
 * is public). Compressed mode (LedFX's default) is a base64 string of
 * interleaved r,g,b bytes; uncompressed mode is [[r...],[g...],[b...]] —
 * SPECTRA never changes LedFX's own transmission_mode config, so both
 * shapes have to be handled here. */
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
