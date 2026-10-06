/** A hand on the drop-sequence layer (drop-detection plan, phase 4):
 * dragging a handle or its line, Shift-dragging the whole sequence, the
 * "＋ Add a drop" click, and the keyboard (C L D · ← → · Enter · Delete ·
 * N P · Ctrl+Z / Ctrl+Y · Escape). ../dropEdit.ts holds the arithmetic;
 * ./useDropEditor.ts does the saving.
 *
 * SMOOTH BY CONSTRUCTION: a drag moves only a GHOST, kept in a ref the
 * canvas layer reads every frame — no React render per pointer move — and
 * ONE save goes out on release with only the handles that changed. The
 * ghost stays drawn where he left it until the saved view arrives, so the
 * handle never jumps back. Keyboard steps move the same ghost and save
 * once, KEY_SAVE_IDLE_MS after the last step.
 *
 * THE KEYBOARD belongs to a drop sequence only while it has the Timeline's
 * attention (`focus`): from a click on a sequence (graph, strip, review
 * list, toolbar) until a click anywhere outside those, Escape, or a click
 * on something else on the graph. Otherwise every key goes on to the
 * page's own trigger and palette keys, exactly as before. */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { FrameGeom } from '../canvas/TimelineCanvas';
import type { DropLive, Hit } from '../canvas/frame';
import { fmtHundredths, type DisplaySeq, type DropRails, type Handle } from '../dropSequences';
import {
  KEY_SAVE_IDLE_MS, addPlacement, changedHandles, clampHandle, dropKeyAction, editable,
  shiftTimes, snapHandle, snapRadiusMs, stepHandle, timesOf, type HandleTimes,
} from '../dropEdit';
import type { DropEditor } from './useDropEditor';

/** A press that moves less than this is a click, not a drag. */
const DRAG_SLOP_PX = 3;

interface DragState {
  key: string;
  handle: Handle;
  whole: boolean;
  orig: HandleTimes;
  x0: number;
  moved: boolean;
}

/** Marks the parts of the page that keep a drop sequence's keyboard focus
 * when clicked (the graph, the strip, the toolbar, the review card). */
export const DROP_FOCUS_ATTR = 'data-drop-focus';

export function useDropSeqInteractions(opts: {
  seqs: DisplaySeq[];
  rails: DropRails | null;
  beatMs: number;
  editor: DropEditor;
  selectedKey: string | null;
  setSelectedKey: (key: string | null) => void;
  onJump: (key: string) => void;
  onShowDetail: () => void;
}) {
  const { seqs, rails, beatMs, editor, selectedKey, setSelectedKey } = opts;
  const live = useRef<DropLive>({ ghost: null, guide: null, addAt: null });
  const drag = useRef<DragState | null>(null);
  const keyEdit = useRef<{ key: string; orig: HandleTimes; timer: ReturnType<typeof setTimeout> | null } | null>(null);
  const [selHandle, setSelHandle] = useState<Handle>('drop');
  const [adding, setAddingState] = useState(false);
  const [focus, setFocus] = useState(false);
  const optsRef = useRef(opts);
  optsRef.current = opts;

  const byKey = useMemo(() => new Map(seqs.map((s) => [s.key, s])), [seqs]);
  const selected = selectedKey ? byKey.get(selectedKey) ?? null : null;

  // A saved ghost is let go of once the saved view is the one drawn.
  useEffect(() => {
    const g = live.current.ghost;
    if (g?.pending) {
      const s = byKey.get(g.key);
      if (!s || (s.charge === g.times.charge && s.lull === g.times.lull && s.drop === g.times.drop)) {
        live.current.ghost = null;
      }
    }
  }, [byKey]);

  const setAdding = useCallback((on: boolean) => {
    setAddingState(on);
    live.current.addAt = null;
    if (on) setFocus(true);
  }, []);

  const select = useCallback((key: string | null, handle: Handle = 'drop') => {
    setSelectedKey(key);
    setSelHandle(handle);
    if (key) setFocus(true);
  }, [setSelectedKey]);

  // Losing focus: a press anywhere outside the drop-sequence surfaces.
  useEffect(() => {
    const down = (ev: PointerEvent) => {
      const t = ev.target as HTMLElement | null;
      if (!t?.closest?.(`[${DROP_FOCUS_ATTR}]`)) setFocus(false);
    };
    document.addEventListener('pointerdown', down, true);
    return () => document.removeEventListener('pointerdown', down, true);
  }, []);

  /** The time a sequence shows right now: its ghost while one is moving. */
  const currentTimes = useCallback((s: DisplaySeq): HandleTimes => {
    const g = live.current.ghost;
    return g && g.key === s.key ? { ...g.times } : timesOf(s);
  }, []);

  const save = useCallback((key: string, orig: HandleTimes, now: HandleTimes, what: string) => {
    const changed = changedHandles(orig, now);
    if (!Object.keys(changed).length) {
      if (live.current.ghost?.key === key) live.current.ghost = null;
      return;
    }
    live.current.ghost = { key, times: now, pending: true };
    void editor.moveHandles(key, changed, what).then((res) => {
      if (res == null && live.current.ghost?.key === key) live.current.ghost = null;
    });
  }, [editor]);

  const flushKeyEdit = useCallback(() => {
    const k = keyEdit.current;
    if (!k) return;
    if (k.timer) clearTimeout(k.timer);
    keyEdit.current = null;
    const g = live.current.ghost;
    live.current.guide = null;
    if (g && g.key === k.key) {
      const handles = Object.keys(changedHandles(k.orig, g.times)).join(' + ');
      save(k.key, k.orig, g.times, `moved ${handles || 'handle'} (keys)`);
    }
  }, [save]);

  useEffect(() => () => { if (keyEdit.current?.timer) clearTimeout(keyEdit.current.timer); }, []);

  // ── the keyboard ────────────────────────────────────────────────────────

  const step = useCallback((handle: Handle, dir: 1 | -1, nudge = false) => {
    const s = selected;
    if (!s || !editable(s)) return;
    const times = currentTimes(s);
    const at = times[handle];
    if (at == null) return;
    const g = stepHandle(handle, at, dir, rails, nudge);
    if (!g) return;
    const ms = clampHandle(times, handle, g.ms);
    const next = { ...times, [handle]: ms };
    if (!keyEdit.current || keyEdit.current.key !== s.key) {
      flushKeyEdit();
      keyEdit.current = { key: s.key, orig: timesOf(s), timer: null };
    }
    live.current.ghost = { key: s.key, times: next };
    live.current.guide = { ...g, ms, what: ms === g.ms ? g.what : `${g.what} (held by the gap)` };
    setSelHandle(handle);
    if (keyEdit.current.timer) clearTimeout(keyEdit.current.timer);
    keyEdit.current.timer = setTimeout(flushKeyEdit, KEY_SAVE_IDLE_MS);
  }, [selected, rails, currentTimes, flushKeyEdit]);

  const what = (s: DisplaySeq) => fmtHundredths(s.drop);

  const onKey = useCallback((e: KeyboardEvent): boolean => {
    const t = e.target as HTMLElement | null;
    if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable)) {
      return false;
    }
    if (!focus) return false;
    const a = dropKeyAction(e);
    if (!a) return false;
    const o = optsRef.current;
    switch (a.kind) {
      case 'escape':
        if (adding) { setAdding(false); return true; }
        flushKeyEdit();
        setFocus(false);
        o.setSelectedKey(null);
        return true;
      case 'undo':
        flushKeyEdit();
        void editor.undo().then((k) => { if (k) select(k); });
        return true;
      case 'redo':
        flushKeyEdit();
        void editor.redo().then((k) => { if (k) select(k); });
        return true;
      case 'sequence': {
        if (!seqs.length) return false;
        const i = selected ? seqs.findIndex((s) => s.key === selected.key) : -1;
        const next = seqs[Math.max(0, Math.min(seqs.length - 1, i < 0 ? (a.dir > 0 ? 0 : seqs.length - 1) : i + a.dir))];
        flushKeyEdit();
        select(next.key);
        o.onJump(next.key);
        return true;
      }
      default:
        break;
    }
    if (!selected) return false;
    if (a.kind === 'select') {
      if (selected[a.handle] == null && currentTimes(selected)[a.handle] == null) return true;
      setSelHandle(a.handle);
      return true;
    }
    if (!editable(selected)) return a.kind === 'step';
    if (a.kind === 'step') { step(selHandle, a.dir, a.nudge); return true; }
    if (a.kind === 'confirm') {
      flushKeyEdit();
      if (selected.look === 'confident' || selected.look === 'suggested') void editor.confirm(selected.key, what(selected));
      return true;
    }
    if (a.kind === 'dismiss') {
      flushKeyEdit();
      void editor.dismiss(selected.key, what(selected));
      return true;
    }
    return false;
  }, [focus, adding, selected, selHandle, seqs, byKey, editor, step, select, setAdding, flushKeyEdit, currentTimes]);

  // ── the pointer ─────────────────────────────────────────────────────────

  const rel = (ev: PointerEvent) => {
    const r = (ev.target as HTMLElement).getBoundingClientRect();
    return { x: ev.clientX - r.left, y: ev.clientY - r.top };
  };

  /** A press on the canvas. True = ours (the page's trigger interactions
   * never see it). */
  const onHit = useCallback((hit: Hit, ev: PointerEvent, g: FrameGeom): boolean => {
    if (adding) {
      const { x } = rel(ev);
      const at = addPlacement(g.xToTime(x), rails, beatMs);
      setAdding(false);
      void editor.add(at.ms).then((key) => { if (key) select(key, 'drop'); });
      return true;
    }
    if (hit?.kind !== 'drop-seq') {
      setFocus(false);
      return false;
    }
    flushKeyEdit();
    select(hit.key, hit.handle);
    const s = byKey.get(hit.key);
    if (!hit.chip && s && editable(s)) {
      drag.current = {
        key: s.key, handle: hit.handle, whole: ev.shiftKey, orig: timesOf(s),
        x0: rel(ev).x, moved: false,
      };
    }
    return true;
  }, [adding, rails, beatMs, editor, byKey, select, setAdding, flushKeyEdit]);

  const onDragMove = useCallback((ev: PointerEvent, g: FrameGeom): boolean => {
    const d = drag.current;
    if (!d) return false;
    const { x } = rel(ev);
    if (!d.moved && Math.abs(x - d.x0) < DRAG_SLOP_PX) return true;
    d.moved = true;
    const ms = g.xToTime(Math.max(0, Math.min(g.w, x)));
    const radius = snapRadiusMs(g.w, g.win.startMs, g.win.endMs);
    const guide = snapHandle(d.handle, ms, rails, radius, ev.altKey);
    let times: HandleTimes;
    let shown = guide;
    if (d.whole) {
      times = shiftTimes(d.orig, guide.ms - (d.orig[d.handle] ?? guide.ms));
    } else {
      const v = clampHandle(d.orig, d.handle, guide.ms);
      times = { ...d.orig, [d.handle]: v };
      if (v !== guide.ms) shown = { ...guide, ms: v, what: `${guide.what} (held by the gap)` };
    }
    live.current.ghost = { key: d.key, times };
    live.current.guide = d.whole ? { ...shown, what: `${shown.what} · whole sequence` } : shown;
    return true;
  }, [rails]);

  const onDragEnd = useCallback((_ev: PointerEvent, _g: FrameGeom): boolean => {
    const d = drag.current;
    if (!d) return false;
    drag.current = null;
    live.current.guide = null;
    const g = live.current.ghost;
    if (!d.moved || !g || g.key !== d.key) {
      if (g && g.key === d.key && !g.pending) live.current.ghost = null;
      return true;
    }
    const label = d.whole ? 'moved the whole sequence' : `moved ${d.handle}`;
    save(d.key, d.orig, g.times, label);
    return true;
  }, [save]);

  const onIdleMove = useCallback((x: number, _y: number, g: FrameGeom) => {
    live.current.addAt = adding ? addPlacement(g.xToTime(x), rails, beatMs) : null;
  }, [adding, rails, beatMs]);

  const cursorFor = useCallback((hit: Hit): string | undefined => {
    if (adding) return 'copy';
    if (hit?.kind !== 'drop-seq') return undefined;
    if (hit.chip) return 'pointer';
    const s = byKey.get(hit.key);
    return s && editable(s) ? 'ew-resize' : 'pointer';
  }, [adding, byKey]);

  const onDoubleHit = useCallback((hit: Hit): boolean => {
    if (hit?.kind !== 'drop-seq') return false;
    select(hit.key, hit.handle);
    optsRef.current.onShowDetail();
    return true;
  }, [select]);

  return {
    live, selHandle, setSelHandle, adding, setAdding, focus, setFocus, select, step,
    flushKeyEdit, onKey, onHit, onDragMove, onDragEnd, onIdleMove, cursorFor, onDoubleHit,
  };
}
