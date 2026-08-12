import { create } from 'zustand';
import { produce, setAutoFreeze } from 'immer';

// Draft trees get _uid attached after each produce(); frozen output would reject that.
setAutoFreeze(false);
import type { Action, MusicEvent } from '../types/events';
import { attachUids, stripUids } from '../lib/uid';
import { findByUid, getAtPath, ROOT_PATH } from '../lib/paths';
import { diffChangedBlocks, FLASH_MS } from '../lib/flashDiff';

interface EditorState {
  draft: MusicEvent | null;
  /** serialized (uid-stripped) JSON at last load/save — dirty = draft differs */
  savedJson: string;
  undoStack: MusicEvent[];
  redoStack: MusicEvent[];
  /** uid → Date.now() of its last create/update; cards flash-fade from it. */
  flashes: Record<string, number>;

  load: (ev: MusicEvent) => void;
  /** All edits funnel through here: snapshots undo, applies an immer recipe.
   * Changed blocks are flash-highlighted — auto-detected unless `flash`
   * names them (pass [] to suppress). */
  mutate: (fn: (d: MusicEvent) => void, flash?: string[]) => void;
  updateAction: (uid: string, fn: (a: Action) => void) => void;
  removeByUid: (uid: string) => void;
  /** Move an action to (containerPath, index); steps reorder within their own list. */
  moveByUid: (uid: string, targetContainer: string, targetIndex: number) => void;
  undo: () => void;
  redo: () => void;
  markSaved: () => void;
  serialize: () => MusicEvent;
}

export const useEditorStore = create<EditorState>((set, get) => ({
  draft: null,
  savedJson: '',
  undoStack: [],
  redoStack: [],
  flashes: {},

  load: (ev) => {
    const draft = attachUids(JSON.parse(JSON.stringify(ev)) as MusicEvent);
    set({
      draft,
      savedJson: JSON.stringify(stripUids(draft)),
      undoStack: [],
      redoStack: [],
      flashes: {},
    });
  },

  mutate: (fn, flash) => {
    const { draft, undoStack } = get();
    if (!draft) return;
    const next = produce(draft, fn);
    attachUids(next); // new objects created inside the recipe need uids too
    const changed = flash ?? diffChangedBlocks(draft, next);
    let flashes = get().flashes;
    if (changed.length) {
      const now = Date.now();
      flashes = Object.fromEntries(
        Object.entries(flashes).filter(([, t]) => now - t < FLASH_MS),
      );
      for (const uid of changed) flashes[uid] = now;
    }
    set({ draft: next, undoStack: [...undoStack.slice(-49), draft], redoStack: [], flashes });
  },

  updateAction: (uid, fn) =>
    get().mutate((d) => {
      const loc = findByUid(d, uid);
      if (loc?.kind === 'action') fn(loc.action);
    }),

  removeByUid: (uid) =>
    get().mutate((d) => {
      const loc = findByUid(d, uid);
      if (!loc) return;
      if (loc.containerPath === ROOT_PATH) {
        d.root = null;
        return;
      }
      const arr = getAtPath(d, loc.containerPath) as unknown[];
      arr.splice(loc.index, 1);
    }),

  moveByUid: (uid, targetContainer, targetIndex) => {
    // Moves keep the item's reference, so auto-detection would flash the
    // containers — flash the moved card itself instead (only on success).
    const flash: string[] = [];
    get().mutate((d) => {
      const loc = findByUid(d, uid);
      if (!loc) return;
      if (loc.containerPath === ROOT_PATH) return; // root card isn't movable
      if (loc.kind !== 'action' && loc.containerPath !== targetContainer) return; // steps stay in their track
      const src = getAtPath(d, loc.containerPath) as unknown[];
      const [item] = src.splice(loc.index, 1);
      const dst = getAtPath(d, targetContainer) as unknown[] | undefined;
      if (!dst) {
        src.splice(loc.index, 0, item); // unknown target — put it back
        return;
      }
      let idx = targetIndex;
      if (src === dst && loc.index < targetIndex) idx -= 1;
      dst.splice(Math.max(0, Math.min(idx, dst.length)), 0, item);
      flash.push(uid);
    }, flash);
  },

  undo: () => {
    const { draft, undoStack, redoStack } = get();
    if (!draft || !undoStack.length) return;
    set({
      draft: undoStack[undoStack.length - 1],
      undoStack: undoStack.slice(0, -1),
      redoStack: [...redoStack, draft],
    });
  },

  redo: () => {
    const { draft, undoStack, redoStack } = get();
    if (!draft || !redoStack.length) return;
    set({
      draft: redoStack[redoStack.length - 1],
      redoStack: redoStack.slice(0, -1),
      undoStack: [...undoStack, draft],
    });
  },

  markSaved: () => {
    const { draft } = get();
    if (draft) set({ savedJson: JSON.stringify(stripUids(draft)) });
  },

  serialize: () => stripUids(get().draft!),
}));

export const useIsDirty = () =>
  useEditorStore((s) => (s.draft ? JSON.stringify(stripUids(s.draft)) !== s.savedJson : false));
