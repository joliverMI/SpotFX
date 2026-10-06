/** EDITING DROP SEQUENCES ON THE TIMELINE — the pure half (drop-detection
 * plan, phase 4: report section 8.2 and 8.4, built to plan.html's working
 * Timeline mock). DOM-free, so scripts/check_drop_sequence_edit.mjs drives
 * it directly. ./dropSequences.ts still decides what each sequence IS; this
 * module decides what a hand on it DOES:
 *
 *   SNAP. A dragged handle snaps to what it belongs on: the DROP to bass
 *   spikes (a hard spike, rise ≥ 0.3, is preferred over a faint one); the
 *   LULL to spikes or beats; the CHARGE to beats, downbeats first, then
 *   spikes. Within SNAP_PX of the pointer; nothing that near — or Alt held —
 *   places it freely on the 20 ms grid. The weights are the mock's own.
 *
 *   STEP. ← → step the selected handle to the previous/next point of its own
 *   rail (drop: spikes; lull: spikes and beats; charge: beats); Shift nudges
 *   10 ms.
 *
 *   ORDER. charge < lull < drop, at least RAMP_FLOOR_MS apart (the engine's
 *   own ramp floor, drop_detector.RAMP_FLOOR_MS) — a handle dragged into its
 *   neighbour stops at the gap, it never pushes the neighbour.
 *
 *   GHOST. While a handle moves, only a ghost moves (the canvas reads it from
 *   a ref every frame — no React render per pointer move); ONE save goes out
 *   on release, carrying only the handles that actually changed.
 *
 *   UNDO. Every save answers his edits before and after it; the stack keeps
 *   UNDO_DEPTH of those pairs per song and an undo/redo puts one side back
 *   through POST /drop-sequences/restore (refused when his edits changed
 *   since, so an undo never silently overwrites a newer edit).
 *
 * Every time is SONG time, the frame the canvas draws in. */
import type { DisplaySeq, DropRails, Handle } from './dropSequences';
import { HANDLES } from './dropSequences';

/** The engine's own ramp floor: the minimum gap between two handles. */
export const RAMP_FLOOR_MS = 200;
/** How near (px) a snap target must be to catch the handle. */
export const SNAP_PX = 14;
/** The free-placement grid (Alt, or nothing to snap to). */
export const FREE_GRID_MS = 20;
/** Shift + ← → nudge. */
export const NUDGE_MS = 10;
/** Undo steps kept per song (the spec asks for at least 20). */
export const UNDO_DEPTH = 50;
/** Keyboard steps that land within this of each other save as ONE edit. */
export const KEY_SAVE_IDLE_MS = 450;
/** Adding a drop: the click goes to the nearest bass spike within this many
 * beats, else exactly where clicked (20 ms grid). */
export const ADD_SNAP_BEATS = 2;

export type SnapRail = 'spike' | 'beat' | 'free';

export interface SnapGuide {
  ms: number;
  /** "bass spike" · "downbeat" · "beat" · "free (20 ms grid)" … */
  what: string;
  rail: SnapRail;
}

export type HandleTimes = Record<Handle, number | null>;

export const grid = (ms: number, step = FREE_GRID_MS) => Math.round(ms / step) * step;

const free = (ms: number): SnapGuide => ({ ms: grid(ms), what: 'free (20 ms grid)', rail: 'free' });

/** The snap radius in ms for SNAP_PX at the canvas's current zoom. */
export function snapRadiusMs(widthPx: number, startMs: number, endMs: number, px = SNAP_PX): number {
  return (px / Math.max(1, widthPx)) * Math.max(1, endMs - startMs);
}

/** Where a handle dragged to `ms` lands (mock: SeqMock.snap). */
export function snapHandle(
  handle: Handle, ms: number, rails: Pick<DropRails, 'spikes' | 'beats'> | null,
  radiusMs: number, freePlace = false,
): SnapGuide {
  if (freePlace || !rails) return free(ms);
  let best: (SnapGuide & { d: number }) | null = null;
  const consider = (c: number, what: string, rail: SnapRail, bias: number) => {
    const d = Math.abs(c - ms) * bias;
    if (d <= radiusMs && (!best || d < best.d)) best = { ms: c, what, rail, d };
  };
  if (handle !== 'charge') {
    for (const [t, rise] of rails.spikes) consider(t, 'bass spike', 'spike', rise >= 0.3 ? 0.8 : 1.1);
  }
  if (handle !== 'drop') {
    for (const [t, down] of rails.beats) {
      consider(t, down ? 'downbeat' : 'beat', 'beat',
        handle === 'charge' ? (down ? 0.7 : 0.9) : 1.2);
    }
  }
  if (handle === 'charge') for (const [t] of rails.spikes) consider(t, 'bass spike', 'spike', 1.15);
  if (!best) return free(ms);
  const { d: _d, ...guide } = best as SnapGuide & { d: number };
  return guide;
}

/** The points a handle steps through with ← → (mock: its keyboard pool). */
export function stepPool(handle: Handle, rails: Pick<DropRails, 'spikes' | 'beats'> | null):
  { ms: number; what: string; rail: SnapRail }[] {
  if (!rails) return [];
  const spikes = rails.spikes.map(([ms]) => ({ ms, what: 'bass spike', rail: 'spike' as const }));
  const beats = rails.beats.map(([ms, down]) => ({ ms, what: down ? 'downbeat' : 'beat', rail: 'beat' as const }));
  const pool = handle === 'drop' ? spikes : handle === 'lull' ? [...spikes, ...beats] : beats;
  return pool.sort((a, b) => a.ms - b.ms);
}

/** The next snap point after (dir 1) or before (dir -1) `ms`; with `nudge`,
 * NUDGE_MS along instead. Null when the rail has nothing further. */
export function stepHandle(
  handle: Handle, ms: number, dir: 1 | -1,
  rails: Pick<DropRails, 'spikes' | 'beats'> | null, nudge = false,
): SnapGuide | null {
  if (nudge) return { ms: ms + dir * NUDGE_MS, what: `nudged ${NUDGE_MS} ms`, rail: 'free' };
  const pool = stepPool(handle, rails);
  const next = dir > 0 ? pool.find((p) => p.ms > ms + 5) : [...pool].reverse().find((p) => p.ms < ms - 5);
  return next ? { ms: next.ms, what: next.what, rail: next.rail } : null;
}

/** `ms` for `handle`, held inside its neighbours with the ramp-floor gap
 * (mock: setMember). A handle never pushes its neighbour. */
export function clampHandle(times: HandleTimes, handle: Handle, ms: number, gap = RAMP_FLOOR_MS): number {
  let v = ms;
  if (handle === 'drop') v = Math.max(v, (times.lull ?? times.charge ?? -Infinity) + gap);
  if (handle === 'lull') {
    v = Math.max(v, (times.charge ?? -Infinity) + gap);
    if (times.drop != null) v = Math.min(v, times.drop - gap);
  }
  if (handle === 'charge') {
    const upper = times.lull ?? times.drop;
    if (upper != null) v = Math.min(v, upper - gap);
  }
  return Math.max(0, Math.round(v));
}

/** Every present handle moved by `delta` (Shift-drag: the whole sequence),
 * never before the song starts. */
export function shiftTimes(times: HandleTimes, delta: number): HandleTimes {
  const first = Math.min(...HANDLES.map((h) => times[h]).filter((v): v is number => v != null));
  const d = Math.max(delta, -first);
  const out = { ...times };
  for (const h of HANDLES) if (out[h] != null) out[h] = Math.round(out[h]! + d);
  return out;
}

export function timesOf(s: Pick<DisplaySeq, 'charge' | 'lull' | 'drop'>): HandleTimes {
  return { charge: s.charge, lull: s.lull, drop: s.drop };
}

/** Only the handles whose time changed — the one save on release. */
export function changedHandles(before: HandleTimes, after: HandleTimes): Partial<Record<Handle, number>> {
  const out: Partial<Record<Handle, number>> = {};
  for (const h of HANDLES) {
    const a = after[h];
    if (a != null && a !== before[h]) out[h] = a;
  }
  return out;
}

/** Can a hand move it? His own triggers are edited on their own strip; a
 * dismissed one is out of play; one that stands down is his trigger's. */
export function editable(s: Pick<DisplaySeq, 'look' | 'fire'>): boolean {
  return s.look !== 'mine' && s.look !== 'dismissed' && s.fire !== 'stands_down';
}

/** The ghost of a sequence being moved: its key and its times right now. */
export interface Ghost {
  key: string;
  times: HandleTimes;
  /** saved, waiting for the server's answer — still drawn where he left it */
  pending?: boolean;
}

/** The display list with the ghost's times laid over its sequence. A
 * detection that moved off the analysis reads as edited, as it will once
 * saved; its dotted lines show where the analysis had each moved handle. */
export function withGhost(seqs: DisplaySeq[], ghost: Ghost | null | undefined): DisplaySeq[] {
  if (!ghost) return seqs;
  return seqs.map((s) => {
    if (s.key !== ghost.key) return s;
    const t = ghost.times;
    const out: DisplaySeq = { ...s, charge: t.charge, lull: t.lull, drop: t.drop ?? s.drop };
    const auto = s.view?.auto;
    if (auto && s.look !== 'added') {
      const had = { ...s.analysisHad };
      let moved = false;
      for (const h of HANDLES) {
        const a = auto[`${h}_ms` as const];
        if (a != null && out[h] != null && Math.abs(out[h]! - a) > 0) {
          had[h] = a;
          moved = true;
        } else if (a != null && out[h] === a) {
          delete had[h];
        }
      }
      out.analysisHad = had;
      if (moved && (s.look === 'confident' || s.look === 'suggested' || s.look === 'confirmed')) {
        out.look = 'edited';
      }
    }
    return out;
  });
}

/** Adding a drop: where a click at `ms` puts it — the nearest bass spike
 * within ADD_SNAP_BEATS beats, else the click itself on the 20 ms grid. */
export function addPlacement(
  ms: number, rails: Pick<DropRails, 'spikes'> | null, beatMs: number,
): SnapGuide {
  const reach = ADD_SNAP_BEATS * (beatMs > 0 ? beatMs : 500);
  let best: [number, number] | null = null;
  for (const sp of rails?.spikes ?? []) {
    const d = Math.abs(sp[0] - ms);
    if (d <= reach && (!best || d < Math.abs(best[0] - ms))) best = sp;
  }
  return best ? { ms: best[0], what: 'bass spike', rail: 'spike' } : free(ms);
}

// ── undo / redo ───────────────────────────────────────────────────────────

/** A single-flight guard: while `run`'s own promise from an earlier call is
 * still settling, a second call never runs `run` again — it resolves to
 * `fallback` right away. This is what keeps undo()/redo() from reading the
 * SAME stale top-of-stack entry twice: a save only reaches the stack
 * (`stacksRef.current`) once its queued POST answers, asynchronously, so a
 * held-down Ctrl+Z firing keydown repeats faster than one round trip would
 * otherwise read the same entry a second time and re-submit it — the
 * duplicate restore then 409s against the first one's own already-advanced
 * rev and wipes the whole stack. `flag` is a plain mutable box (a React ref
 * in practice): checked and set synchronously at call time, so there is no
 * gap for a second call to slip through before the first has claimed it. */
export function guardInFlight<T>(
  flag: { current: boolean }, run: () => Promise<T>, fallback: T,
): Promise<T> {
  if (flag.current) return Promise.resolve(fallback);
  flag.current = true;
  return run().finally(() => { flag.current = false; });
}

/** His edits on one song, as the server keeps them. */
export interface DropEdits {
  overrides: Record<string, unknown>;
  added: unknown[];
}

export interface UndoEntry {
  label: string;
  before: DropEdits;
  after: DropEdits;
  revBefore: string;
  revAfter: string;
  /** the sequence to select again when this step is undone/redone */
  key: string | null;
}

export interface UndoStacks {
  undo: UndoEntry[];
  redo: UndoEntry[];
}

export const EMPTY_STACKS: UndoStacks = { undo: [], redo: [] };

/** A new edit: on the undo stack (capped), and the redo stack cleared. A
 * save that changed nothing adds no step. */
export function pushEdit(st: UndoStacks, e: UndoEntry, depth = UNDO_DEPTH): UndoStacks {
  if (e.revBefore === e.revAfter) return st;
  return { undo: [...st.undo, e].slice(-depth), redo: [] };
}

/** After an undo landed: the step moves to the redo stack. */
export function afterUndo(st: UndoStacks): UndoStacks {
  const e = st.undo[st.undo.length - 1];
  if (!e) return st;
  return { undo: st.undo.slice(0, -1), redo: [...st.redo, e] };
}

/** After a redo landed: the step moves back to the undo stack. */
export function afterRedo(st: UndoStacks): UndoStacks {
  const e = st.redo[st.redo.length - 1];
  if (!e) return st;
  return { undo: [...st.undo, e], redo: st.redo.slice(0, -1) };
}

/** What an undo sends: put `before` back, only if his edits are still `after`. */
export function undoRequest(e: UndoEntry) {
  return { edits: e.before, expect: e.revAfter };
}

export function redoRequest(e: UndoEntry) {
  return { edits: e.after, expect: e.revBefore };
}

// ── the keyboard ──────────────────────────────────────────────────────────

export type DropKeyAction =
  | { kind: 'select'; handle: Handle }
  | { kind: 'step'; dir: 1 | -1; nudge: boolean }
  | { kind: 'confirm' }
  | { kind: 'dismiss' }
  | { kind: 'sequence'; dir: 1 | -1 }
  | { kind: 'undo' }
  | { kind: 'redo' }
  | { kind: 'escape' };

/** What a key does while a drop sequence has the Timeline's keyboard
 * (report section 8.2): C L D pick a handle, ← → step it (Shift nudges),
 * Enter confirms, Delete dismisses, N P go to the next/previous sequence,
 * Ctrl/Cmd+Z undo, Ctrl/Cmd+Y or Shift+Z redo, Escape lets go. Null = not
 * ours; the page's other keys get it. */
export function dropKeyAction(e: {
  key: string; shiftKey?: boolean; ctrlKey?: boolean; metaKey?: boolean; altKey?: boolean;
}): DropKeyAction | null {
  const k = e.key.length === 1 ? e.key.toLowerCase() : e.key;
  if ((e.ctrlKey || e.metaKey) && !e.altKey) {
    if (k === 'z' && !e.shiftKey) return { kind: 'undo' };
    if (k === 'y' || (k === 'z' && e.shiftKey)) return { kind: 'redo' };
    return null;
  }
  if (e.ctrlKey || e.metaKey || e.altKey) return null;
  if (k === 'c') return { kind: 'select', handle: 'charge' };
  if (k === 'l') return { kind: 'select', handle: 'lull' };
  if (k === 'd') return { kind: 'select', handle: 'drop' };
  if (k === 'ArrowLeft') return { kind: 'step', dir: -1, nudge: !!e.shiftKey };
  if (k === 'ArrowRight') return { kind: 'step', dir: 1, nudge: !!e.shiftKey };
  if (k === 'Enter') return { kind: 'confirm' };
  if (k === 'Delete' || k === 'Backspace') return { kind: 'dismiss' };
  if (k === 'n') return { kind: 'sequence', dir: 1 };
  if (k === 'p') return { kind: 'sequence', dir: -1 };
  if (k === 'Escape') return { kind: 'escape' };
  return null;
}

/** The server's error, without the method/URL/status prefix. */
export function editErrorText(err: unknown): string {
  const msg = err instanceof Error ? err.message : String(err);
  const m = msg.match(/→ \d+: (.*)$/s);
  return m ? m[1] : msg;
}
