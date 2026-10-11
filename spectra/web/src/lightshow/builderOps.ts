/** Pure helpers for the Light Show builders (LightShowPage.tsx's Set editor
 * and SequenceView.tsx's Sequence builder), kept DOM-free so
 * scripts/check_light_show_builder.mjs drives them directly.
 *
 *   * SET REFERENCES — the client half of spectra/services/show_refs.py:
 *     which sets a set calls, and whether picking a set for a "Run another
 *     set" step would make the set call itself. The server is the authority
 *     (it refuses the save); this only keeps such a set out of the picker.
 *   * ONE-LINE SUMMARIES — what a collapsed step or item says.
 *   * THE CLIPBOARD — copy steps / sequence items / whole sets and paste
 *     them into any set or sequence, in this tab or another (localStorage,
 *     the legacy SpotFX editor's `spotfx.clipboard.v1` precedent). Only each
 *     pasted step/item's OWN id is regenerated (`cloneFresh`, below), so two
 *     pastes are two independent steps — a nested reference (a `target`'s
 *     own `{kind, id}`, `set_id`, `params.set`) is never touched, or a paste
 *     would silently retarget a different fixture/category/set. */
import type { SequenceItem, ShowAction, ShowKind, ShowSet } from './types';
import { ARM_LABEL, WAIT_LABEL, clock } from './sequenceOps';

export const CALL_KIND = 'call_set';

export function newStepId(): string {
  return Math.random().toString(16).slice(2, 14);
}

// ── set references ─────────────────────────────────────────────────────────

/** The sets these steps call, in order, without repeats. */
export function calledIds(actions: ShowAction[]): string[] {
  const out: string[] = [];
  for (const a of actions) {
    const sid = a.kind === CALL_KIND ? a.params?.set : undefined;
    if (typeof sid === 'string' && sid && !out.includes(sid)) out.push(sid);
  }
  return out;
}

/** Every set reachable from `fromId` through calls (fromId excluded unless
 * a loop returns to it). `override` lets the set being edited use its
 * unsaved steps. */
export function reachable(fromId: string, sets: ShowSet[], override?: { id: string; actions: ShowAction[] }): Set<string> {
  const byId = new Map(sets.filter((s) => s.id).map((s) => [s.id as string, s]));
  const stepsOf = (id: string) => (override && override.id === id ? override.actions : byId.get(id)?.actions ?? []);
  const seen = new Set<string>();
  const stack = [...calledIds(stepsOf(fromId))];
  while (stack.length) {
    const id = stack.pop() as string;
    if (seen.has(id)) continue;
    seen.add(id);
    stack.push(...calledIds(stepsOf(id)));
  }
  return seen;
}

/** Would set `currentId` calling `candidateId` make it call itself? */
export function wouldCycle(currentId: string | undefined, candidateId: string, sets: ShowSet[]): boolean {
  if (!currentId) return false;
  if (candidateId === currentId) return true;
  return reachable(candidateId, sets).has(currentId);
}

/** The sets a "Run another set" step may pick: every other saved set that
 * does not (directly or indirectly) call this one. */
export function callableSets(currentId: string | undefined, sets: ShowSet[]): ShowSet[] {
  return sets.filter((s) => s.id && !wouldCycle(currentId, s.id, sets));
}

/** The sets that call `id` directly (the "used by" line, computed locally
 * for a set the server has not described yet). */
export function callersOf(id: string, sets: ShowSet[]): ShowSet[] {
  return sets.filter((s) => s.id !== id && calledIds(s.actions).includes(id));
}

// ── summaries ──────────────────────────────────────────────────────────────

export interface SummaryLookups {
  sets?: Map<string, string>;
  scenes?: Map<string, string>;
  colorSets?: Map<string, string>;
  fixtures?: Map<string, string>;
  houseModes?: Map<string, string>;
}

function word(v: unknown): string {
  if (typeof v === 'boolean') return v ? 'on' : 'off';
  if (typeof v === 'number') return Number.isInteger(v) ? String(v) : String(Math.round(v * 100) / 100);
  if (typeof v === 'string') return v.replace(/_/g, ' ');
  return '';
}

/** What a collapsed step says after its kind's label: its parameters, in
 * his words where a name is known ("Fixture: Porch Rail · level 0.4"). */
export function stepSummary(a: ShowAction, kind: ShowKind | undefined, look: SummaryLookups = {}): string {
  if (!kind) return a.kind;
  if (a.kind === CALL_KIND) {
    const sid = a.params?.set as string | undefined;
    if (!sid) return 'no set chosen';
    return look.sets?.get(sid) ? `“${look.sets.get(sid)}”` : 'a set that no longer exists';
  }
  const parts: string[] = [];
  for (const p of kind.params) {
    const v = a.params?.[p.name];
    if (v === undefined || v === null || v === '') continue;
    let text = '';
    switch (p.type) {
      case 'target': {
        const t = v as { kind?: string; id?: string | null };
        if (t.kind === 'everything' || !t.kind) text = 'everything';
        else if (t.kind === 'fixture') text = look.fixtures?.get(String(t.id)) ?? String(t.id ?? '?');
        else text = String(t.id ?? '?');
        break;
      }
      case 'scene': text = look.scenes?.get(String(v)) ?? String(v); break;
      case 'color_set': text = look.colorSets?.get(String(v)) ?? String(v); break;
      case 'house_mode': text = look.houseModes?.get(String(v)) ?? String(v); break;
      case 'scenes': case 'color_sets': case 'hue_areas': {
        const list = v as string[];
        const m = p.type === 'scenes' ? look.scenes : p.type === 'color_sets' ? look.colorSets : undefined;
        text = list.length > 2 ? `${list.length} ${p.label.toLowerCase()}`
          : list.map((x) => m?.get(x) ?? x).join(', ');
        break;
      }
      case 'overrides': {
        const n = Object.keys(v as object).length;
        text = n ? `${n} override${n === 1 ? '' : 's'}` : '';
        break;
      }
      case 'color': text = String(v); break;
      default: {
        const w = word(v);
        if (p.type === 'bool' && (p.name === 'on' || p.name === 'enabled')) text = w;
        else text = p.type === 'number' || p.type === 'bool' ? `${p.label.toLowerCase()} ${w}${p.unit ? ` ${p.unit}` : ''}` : w;
      }
    }
    if (text) parts.push(text);
    if (parts.length >= 4) break;
  }
  return parts.join(' · ');
}

/** What a collapsed sequence item says. */
export function itemSummary(it: SequenceItem, setNames: Map<string, string>): string {
  if (it.kind === 'set') {
    const name = it.set_id ? (setNames.get(it.set_id) ?? 'a deleted set') : 'no set chosen';
    return `${name} — ${ARM_LABEL[it.arm].split(' — ')[0]}`;
  }
  const w = it.wait;
  if (!w) return 'Wait';
  switch (w.kind) {
    case 'duration': return `Wait ${clock(w.seconds)}`;
    case 'trigger_count': return `Wait for ${w.count} ${({ scene_change: 'scene change', high: 'High Trigger', low: 'Low Trigger' } as Record<string, string>)[w.trigger]}${w.count === 1 ? '' : 's'}`;
    case 'songs': return `Wait for ${w.count} song${w.count === 1 ? '' : 's'}`;
    case 'song_list': return w.songs.length
      ? `Wait for ${w.songs.slice(0, 2).map((s) => s.title).join(' or ')}${w.songs.length > 2 ? ` or ${w.songs.length - 2} more` : ''}`
      : WAIT_LABEL.song_list;
    default: return 'Wait';
  }
}

// ── list edits ─────────────────────────────────────────────────────────────

/** Deep copy with only each cloned list element's OWN top-level `id`
 * regenerated — a step/item's identity, nothing nested inside it. `set_id`,
 * `params.set` and every other reference (including a `target` param's own
 * `{kind, id}`) are untouched: those name something ELSE a step points at,
 * not the step itself, and must survive a duplicate/paste unchanged or the
 * copy silently retargets at a different fixture/category/set. */
export function cloneFresh<T>(data: T): T {
  const copy = JSON.parse(JSON.stringify(data));
  const freshenId = (v: unknown): unknown => {
    if (v && typeof v === 'object' && !Array.isArray(v) && typeof (v as Record<string, unknown>).id === 'string') {
      (v as Record<string, unknown>).id = newStepId();
    }
    return v;
  };
  if (Array.isArray(copy)) return (copy as unknown[]).map(freshenId) as T;
  return freshenId(copy) as T;
}

/** Strip the server's per-item annotations before a copy or a save. */
export function plainItem(it: SequenceItem): SequenceItem {
  const { title: _t, problems: _p, ...rest } = it;
  return rest;
}

export function duplicateAt<T extends { id?: string }>(list: T[], i: number): T[] {
  const out = list.slice();
  out.splice(i + 1, 0, cloneFresh(list[i]));
  return out;
}

export function insertAt<T>(list: T[], at: number, items: T[]): T[] {
  const out = list.slice();
  out.splice(Math.max(0, Math.min(out.length, at)), 0, ...items);
  return out;
}

// ── the clipboard ──────────────────────────────────────────────────────────

export const CLIP_KEY = 'spectra.lightshow.clipboard.v1';

export type ShowClip =
  | { kind: 'steps'; steps: ShowAction[]; summary: string; set_name?: string; copied_at: string }
  | { kind: 'items'; items: SequenceItem[]; summary: string; copied_at: string };

type ClipBody = { kind: 'steps'; steps: ShowAction[]; summary: string; set_name?: string }
  | { kind: 'items'; items: SequenceItem[]; summary: string };

const listeners = new Set<() => void>();

export function writeClip(clip: ClipBody): void {
  const full = { ...clip, copied_at: new Date().toISOString() } as ShowClip;
  try { localStorage.setItem(CLIP_KEY, JSON.stringify(full)); } catch { /* private mode */ }
  listeners.forEach((fn) => fn());
}

export function readClip(): ShowClip | null {
  try {
    const raw = localStorage.getItem(CLIP_KEY);
    return raw ? (JSON.parse(raw) as ShowClip) : null;
  } catch {
    return null;
  }
}

export function subscribeClip(fn: () => void): () => void {
  listeners.add(fn);
  const onStorage = (e: StorageEvent) => { if (e.key === CLIP_KEY) fn(); };
  if (typeof window !== 'undefined') window.addEventListener('storage', onStorage);
  return () => {
    listeners.delete(fn);
    if (typeof window !== 'undefined') window.removeEventListener('storage', onStorage);
  };
}

/** "Copy set" names it "<name> copy"-style on a paste as a new set. */
export function pasteSetName(base: string, existing: string[]): string {
  const taken = new Set(existing.map((n) => n.trim().toLowerCase()));
  let out = base;
  for (let n = 2; taken.has(out.trim().toLowerCase()); n++) out = `${base} ${n}`;
  return out;
}
