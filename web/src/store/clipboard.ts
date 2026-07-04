/** Cross-event clipboard: localStorage-backed so copies survive navigation,
 * reloads, and work across tabs (key `spotfx.clipboard.v1`). All `id` fields
 * are regenerated on paste so dedupe keys stay unique per instance. */
import { useSyncExternalStore } from 'react';
import { stripUids, uuid } from '../lib/uid';

const KEY = 'spotfx.clipboard.v1';

export type ClipKind = 'action' | 'sequence_child' | 'parallel_child' | 'random_option';

export interface Clip {
  kind: ClipKind;
  data: unknown;
  summary: string;
  copiedAt: string;
}

const listeners = new Set<() => void>();
const notify = () => listeners.forEach((fn) => fn());

if (typeof window !== 'undefined') {
  window.addEventListener('storage', (e) => {
    if (e.key === KEY) notify();
  });
}

export function writeClip(kind: ClipKind, data: unknown, summary: string): void {
  const clip: Clip = { kind, data: stripUids(data), summary, copiedAt: new Date().toISOString() };
  localStorage.setItem(KEY, JSON.stringify(clip));
  notify();
}

export function readClip(): Clip | null {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as Clip) : null;
  } catch {
    return null;
  }
}

/** Deep-clone with every `id` field regenerated (dedupe keys must be unique
 * per pasted instance). `event_id` and other *_id fields are untouched. */
export function cloneForPaste<T>(data: T): T {
  const walk = (v: unknown): unknown => {
    if (Array.isArray(v)) return v.map(walk);
    if (v && typeof v === 'object') {
      const o: Record<string, unknown> = {};
      for (const [k, val] of Object.entries(v as Record<string, unknown>)) {
        o[k] = k === 'id' && typeof val === 'string' ? uuid() : walk(val);
      }
      return o;
    }
    return v;
  };
  return walk(JSON.parse(JSON.stringify(data))) as T;
}

/** Reactive clipboard state for enabling paste buttons (updates across tabs). */
export function useClipboard(): Clip | null {
  return useSyncExternalStore(
    (cb) => {
      listeners.add(cb);
      return () => listeners.delete(cb);
    },
    () => localStorage.getItem(KEY),
    () => null,
  ) ? readClip() : null;
}
