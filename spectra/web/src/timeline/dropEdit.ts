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
 *   THE PRE-DROP (predrop plan step 4), the fourth handle. It snaps to the
 *   rail of its KIND — a spike to the HITS (every high-band attack), a vocal
 *   intro to the vocal ENTRIES — and is held inside its kind's lead range
 *   before the drop (PRE_DROP_LEAD_MS, the server's own check), which also
 *   keeps it the ramp floor before the drop. It may sit before the lull
 *   starts. A drop dragged back past it is held by a pre-drop he PLACED and
 *   leaves an automatic one out (the server's rule for an automatic lull); a
 *   whole-sequence move carries it. R selects it, K switches its kind. On
 *   one of his own sequences it is the only handle the Timeline moves
 *   (`editableHandle`).
 *
 * Every time is SONG time, the frame the canvas draws in. */
import type { DisplaySeq, DropRails, Handle, PreDropKind, SeqHandle, SeqTimes } from './dropSequences';
import { HANDLES, SEQ_HANDLES } from './dropSequences';

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

/** What a snapped handle sits on: a bass spike or a beat (the phases), a
 * hit or a vocal entry (the pre-drop), or nothing (the free grid). */
export type SnapRail = 'spike' | 'beat' | 'hit' | 'entry' | 'free';

export interface SnapGuide {
  ms: number;
  /** "bass spike" · "downbeat" · "beat" · "hit" · "vocal entry" · "free (20 ms grid)" … */
  what: string;
  rail: SnapRail;
}

/** A sequence's handle times. The pre-drop is optional: a caller with no
 * pre-drop (Home's in-place editor) passes the three phases alone. */
export type HandleTimes = Record<Handle, number | null> & { pre_drop?: number | null };

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
 * (mock: setMember). A handle never pushes its neighbour. A drop is held
 * the gap after `times.pre_drop` too when one is given — pass it only for a
 * pre-drop he PLACED (`clampBasis`): an automatic one is left out instead. */
export function clampHandle(times: HandleTimes, handle: Handle, ms: number, gap = RAMP_FLOOR_MS): number {
  let v = ms;
  if (handle === 'drop') {
    v = Math.max(v, (times.lull ?? times.charge ?? -Infinity) + gap);
    if (times.pre_drop != null) v = Math.max(v, times.pre_drop + gap);
  }
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

/** The times a phase handle's order clamp holds it against: a pre-drop he
 * placed holds the drop back (the server refuses the move), an automatic
 * one does not (a drop moved past it simply leaves it out, as the server's
 * view does with an automatic lull). */
export function clampBasis(times: HandleTimes, preDropPlaced: boolean): HandleTimes {
  return preDropPlaced || times.pre_drop == null ? times : { ...times, pre_drop: null };
}

/** Every present handle — the pre-drop too — moved by `delta` (Shift-drag:
 * the whole sequence), never before the song starts. */
export function shiftTimes(times: HandleTimes, delta: number): HandleTimes {
  const first = Math.min(...SEQ_HANDLES.map((h) => times[h]).filter((v): v is number => v != null));
  const d = Math.max(delta, -first);
  const out = { ...times };
  for (const h of SEQ_HANDLES) if (out[h] != null) out[h] = Math.round(out[h]! + d);
  return out;
}

export function timesOf(s: SeqTimes): HandleTimes {
  return { charge: s.charge, lull: s.lull, drop: s.drop, pre_drop: s.pre_drop ?? null };
}

/** Only the handles whose time changed — the one save on release. */
export function changedHandles(before: HandleTimes, after: HandleTimes): Partial<Record<SeqHandle, number>> {
  const out: Partial<Record<SeqHandle, number>> = {};
  for (const h of SEQ_HANDLES) {
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

/** Can a hand move this one handle? As `editable`, except the pre-drop of
 * one of HIS OWN sequences: his charge, lull and drop are his triggers
 * (moved on their own strip), but the pre-drop before his drop lives in the
 * drop store, so it is edited here through his "his:<drop id>" key. */
export function editableHandle(s: Pick<DisplaySeq, 'look' | 'fire'>, h: SeqHandle): boolean {
  if (h === 'pre_drop') return s.look !== 'dismissed' && s.fire !== 'stands_down';
  return editable(s);
}

// ── the pre-drop's own rails and range ───────────────────────────────────

/** How far before its drop a pre-drop of each kind may sit — its search
 * window, as wide as any scene may set (predrop_detector.lead_range; the
 * server refuses a drag, a kind switch or ＋ Pre-drop outside it). Both
 * floors sit above the ramp floor, so a pre-drop inside its range is always
 * at least RAMP_FLOOR_MS before its drop. */
export const PRE_DROP_LEAD_MS: Record<PreDropKind, [number, number]> = {
  spike: [250, 3000], intro: [350, 4500],
};

const PRE_DROP_RAIL_WORD: Record<PreDropKind, string> = { spike: 'hit', intro: 'vocal entry' };
const PRE_DROP_SNAP: Record<PreDropKind, SnapRail> = { spike: 'hit', intro: 'entry' };

/** The rail a pre-drop of `kind` snaps to: a spike to the hits, a vocal
 * intro to the vocal entries. */
export function preDropRail(
  kind: PreDropKind, rails: Pick<DropRails, 'hits' | 'entries'> | null | undefined,
): [number, number][] {
  if (!rails) return [];
  return (kind === 'intro' ? rails.entries : rails.hits) ?? [];
}

/** Where a pre-drop dragged to `ms` lands: the nearest point on its kind's
 * rail within `radiusMs`, else — or with Alt — the 20 ms grid. */
export function snapPreDrop(
  kind: PreDropKind, ms: number, rails: Pick<DropRails, 'hits' | 'entries'> | null | undefined,
  radiusMs: number, freePlace = false,
): SnapGuide {
  if (freePlace) return free(ms);
  let best: { ms: number; d: number } | null = null;
  for (const [t] of preDropRail(kind, rails)) {
    const d = Math.abs(t - ms);
    if (d <= radiusMs && (!best || d < best.d)) best = { ms: t, d };
  }
  return best ? { ms: best.ms, what: PRE_DROP_RAIL_WORD[kind], rail: PRE_DROP_SNAP[kind] } : free(ms);
}

/** ← → for the pre-drop: the next point on its kind's rail after (dir 1) or
 * before (dir -1) `ms`; with `nudge`, NUDGE_MS along. Null when the rail has
 * nothing further. */
export function stepPreDrop(
  kind: PreDropKind, ms: number, dir: 1 | -1,
  rails: Pick<DropRails, 'hits' | 'entries'> | null | undefined, nudge = false,
): SnapGuide | null {
  if (nudge) return { ms: ms + dir * NUDGE_MS, what: `nudged ${NUDGE_MS} ms`, rail: 'free' };
  const pool = preDropRail(kind, rails).map(([t]) => t).sort((a, b) => a - b);
  const next = dir > 0 ? pool.find((t) => t > ms + 5) : [...pool].reverse().find((t) => t < ms - 5);
  return next == null ? null : { ms: next, what: PRE_DROP_RAIL_WORD[kind], rail: PRE_DROP_SNAP[kind] };
}

/** `ms` held inside its kind's lead range before the drop — never closer
 * than the ramp floor — and never before the song starts. It may sit
 * before the lull. */
export function clampPreDrop(kind: PreDropKind, dropMs: number, ms: number, gap = RAMP_FLOOR_MS): number {
  const [lo, hi] = PRE_DROP_LEAD_MS[kind];
  const v = Math.min(Math.max(ms, dropMs - hi), dropMs - Math.max(lo, gap));
  return Math.max(0, Math.round(v));
}

/** Whether a pre-drop `leadMs` before its drop fits `kind`'s lead range —
 * the kind switch's own test (the server refuses one that does not). */
export function preDropKindFits(kind: PreDropKind, leadMs: number): boolean {
  const [lo, hi] = PRE_DROP_LEAD_MS[kind];
  return leadMs >= lo && leadMs <= hi;
}

export const OTHER_PRE_DROP_KIND: Record<PreDropKind, PreDropKind> = { spike: 'intro', intro: 'spike' };

/** The ghost of a sequence being moved: its key and its times right now. */
export interface Ghost {
  key: string;
  times: HandleTimes;
  /** saved, waiting for the server's answer — still drawn where he left it */
  pending?: boolean;
}

/** The display list with the ghost's times laid over its sequence. A
 * detection that moved off the analysis reads as edited, as it will once
 * saved; its dotted lines show where the analysis had each moved handle.
 * The pre-drop rides the ghost too: moved off the rules' place it gets its
 * dotted line, and an AUTOMATIC one the drop was dragged back past is left
 * out, exactly as the saved view will leave it. On one of his own
 * sequences only the pre-drop can move, so only its line is touched. */
export function withGhost(seqs: DisplaySeq[], ghost: Ghost | null | undefined): DisplaySeq[] {
  if (!ghost) return seqs;
  return seqs.map((s) => {
    if (s.key !== ghost.key) return s;
    const t = ghost.times;
    const drop = t.drop ?? s.drop;
    const preIn = t.pre_drop !== undefined ? t.pre_drop : s.pre_drop;
    const pre = preIn != null && preIn > drop - RAMP_FLOOR_MS ? null : preIn;
    const out: DisplaySeq = { ...s, charge: t.charge, lull: t.lull, drop, pre_drop: pre };
    const had = { ...s.analysisHad };
    let moved = false;
    const auto = s.view?.auto;
    if (auto && s.look !== 'added' && s.look !== 'mine') {
      for (const h of HANDLES) {
        const a = auto[`${h}_ms` as const];
        if (a != null && out[h] != null && Math.abs(out[h]! - a) > 0) {
          had[h] = a;
          moved = true;
        } else if (a != null && out[h] === a) {
          delete had[h];
        }
      }
    }
    const preAuto = s.preDrop?.auto ?? null;
    if (preAuto != null && !s.preDrop?.off && t.pre_drop !== undefined && t.pre_drop !== s.pre_drop) {
      if (pre != null && pre !== preAuto) {
        had.pre_drop = preAuto;
        moved = true;
      } else if (pre === preAuto) {
        delete had.pre_drop;
      }
    }
    out.analysisHad = had;
    if (moved && (s.look === 'confident' || s.look === 'suggested' || s.look === 'confirmed')) {
      out.look = 'edited';
    }
    return out;
  });
}

/** Whether the saved view has caught up with a saved ghost (the ghost can
 * then be let go of): every handle drawn where the ghost draws it. */
export function ghostLanded(s: DisplaySeq, ghost: Ghost): boolean {
  if (s.key !== ghost.key) return false;
  const shown = withGhost([s], ghost)[0];
  return SEQ_HANDLES.every((h) => s[h] === shown[h]);
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

/** One row of his triggers a Drops-panel write changed (the root route's
 * undo record, services/profile_trigger_edit.py — or, for a trigger born on
 * SPECTRA's own trigger card, the fired copy's, `store: 'fired'`): the
 * trigger as it was (`before`), as it is (`after`), and where it sat. */
export interface ProfileChange {
  id: string;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  index: number | null;
  did?: string;
  store?: 'fired';
}

/** One restore record: a row from `from` back to `to` (its store kept). */
function restoreRecord(c: ProfileChange, from: ProfileChange['before'], to: ProfileChange['before']) {
  return { id: c.id, from, to, index: c.index, ...(c.store ? { store: c.store } : {}) };
}

export interface UndoEntry {
  label: string;
  before: DropEdits;
  after: DropEdits;
  revBefore: string;
  revAfter: string;
  /** the sequence to select again when this step is undone/redone */
  key: string | null;
  /** HIS OWN DROP's half of the step (the Home Drops panel): the song-
   * profile rows the write changed, put back with the drop store's pair
   * (spectra/services/drop_panel.py's ONE UNDO STEP). */
  profile?: ProfileChange[];
}

export interface UndoStacks {
  undo: UndoEntry[];
  redo: UndoEntry[];
}

export const EMPTY_STACKS: UndoStacks = { undo: [], redo: [] };

/** Whether an edit changed anything: his drop-store edits moved, or (one
 * of his own drops) his song profile did. A property of the edit alone, so
 * it can be read before any state update has run. */
export function editChanged(e: UndoEntry): boolean {
  return e.revBefore !== e.revAfter || !!(e.profile && e.profile.length);
}

/** A new edit: on the undo stack (capped), and the redo stack cleared. A
 * save that changed nothing adds no step. */
export function pushEdit(st: UndoStacks, e: UndoEntry, depth = UNDO_DEPTH): UndoStacks {
  if (!editChanged(e)) return st;
  return { undo: [...st.undo, e].slice(-depth), redo: [] };
}

/** `pushEdit`, plus whether it actually changed anything — the same
 * identity check (the stacks object coming back unchanged) as the single
 * source of truth for whether a "it worked" note should show. A save that
 * no-oped (e.g. a placement his explicit press refuses instead, or an
 * already-his sequence re-confirmed) earns neither a step nor a note. */
export function pushEditChanged(st: UndoStacks, e: UndoEntry): [UndoStacks, boolean] {
  const next = pushEdit(st, e);
  return [next, next !== st];
}

/** Two steps as ONE (the Drops panel's double-tap, his Q9: "the pair is one
 * undo step"): from `a`'s before to `b`'s after, and each of his trigger rows
 * from the first change's before to the last change's after (a row both
 * steps changed back to what it was drops out). */
export function mergeEntries(a: UndoEntry, b: UndoEntry): UndoEntry {
  const byId = new Map<string, ProfileChange>();
  const order: string[] = [];
  for (const c of [...(a.profile ?? []), ...(b.profile ?? [])]) {
    const seen = byId.get(c.id);
    if (seen) byId.set(c.id, { ...seen, after: c.after, did: c.did ?? seen.did });
    else { byId.set(c.id, { ...c }); order.push(c.id); }
  }
  const profile = order.map((id) => byId.get(id)!)
    .filter((c) => JSON.stringify(c.before) !== JSON.stringify(c.after));
  return {
    label: b.label, before: a.before, after: b.after, revBefore: a.revBefore,
    revAfter: b.revAfter, key: b.key ?? a.key, ...(profile.length ? { profile } : {}),
  };
}

/** `pushEdit`, but folded into the step on top when `e` continues it (same
 * drop, starting where that step ended) — a double-tap's second write. A
 * pair that ends where it began leaves no step at all. */
export function mergeEdit(st: UndoStacks, e: UndoEntry, depth = UNDO_DEPTH): UndoStacks {
  const top = st.undo[st.undo.length - 1];
  if (!top || top.revAfter !== e.revBefore || top.key !== e.key) return pushEdit(st, e, depth);
  const merged = mergeEntries(top, e);
  const rest = st.undo.slice(0, -1);
  return { undo: editChanged(merged) ? [...rest, merged] : rest, redo: [] };
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

/** What an undo sends: put `before` back, only if his edits are still
 * `after` — and, for one of his own drops, every profile row back from
 * what the write left to what it was. */
export function undoRequest(e: UndoEntry) {
  const out: { edits: DropEdits; expect: string; profile?: unknown[] } =
    { edits: e.before, expect: e.revAfter };
  if (e.profile && e.profile.length) {
    out.profile = e.profile.map((c) => restoreRecord(c, c.after, c.before));
  }
  return out;
}

export function redoRequest(e: UndoEntry) {
  const out: { edits: DropEdits; expect: string; profile?: unknown[] } =
    { edits: e.after, expect: e.revBefore };
  if (e.profile && e.profile.length) {
    out.profile = e.profile.map((c) => restoreRecord(c, c.before, c.after));
  }
  return out;
}

// ── the keyboard ──────────────────────────────────────────────────────────

export type DropKeyAction =
  | { kind: 'select'; handle: SeqHandle }
  | { kind: 'step'; dir: 1 | -1; nudge: boolean }
  | { kind: 'pre_drop_kind' }
  | { kind: 'confirm' }
  | { kind: 'dismiss' }
  | { kind: 'sequence'; dir: 1 | -1 }
  | { kind: 'undo' }
  | { kind: 'redo' }
  | { kind: 'escape' };

/** What a key does while a drop sequence has the Timeline's keyboard
 * (report section 8.2): C L D pick a handle and R the pre-drop (P is taken:
 * previous), ← → step it (Shift nudges), K switches the pre-drop's kind
 * (spike ⇄ vocal intro), Enter confirms, Delete dismisses, N P go to the
 * next/previous sequence, Ctrl/Cmd+Z undo, Ctrl/Cmd+Y or Shift+Z redo,
 * Escape lets go. Null = not ours; the page's other keys get it. */
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
  if (k === 'r') return { kind: 'select', handle: 'pre_drop' };
  if (k === 'k') return { kind: 'pre_drop_kind' };
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
