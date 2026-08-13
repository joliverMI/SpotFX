import { create } from 'zustand';
import { produce, setAutoFreeze } from 'immer';
import { apiPost } from '../api/spotfx';
import type { MusicTrigger, SongProfile } from './types';

setAutoFreeze(false);

export interface TrackInfo {
  uri: string;
  title: string;
  artist: string;
  duration_ms: number;
  is_playing: boolean;
}

interface BuilderState {
  /** Live track from WS (live mode) */
  track: TrackInfo | null;
  /** Explicitly selected song (standard mode); null = follow live track */
  manualUri: string | null;
  liveMode: boolean;
  autoWait: boolean;

  profile: SongProfile | null;
  dirty: boolean;
  slotId: string; // '' = Default triggers; else setlist id

  editingTriggerId: string | null; // 'new:<ms>' opens create dialog
  armedKey: string | null;
  activePaletteId: string | null;
  /** Override Blend brush: "[" arms set, "]" arms clear; right-click a
   * trigger to paint it. Escape disarms. Takes precedence over the armed
   * palette event while active. */
  blendBrush: 'set' | 'clear' | null;
  /** Multi-selected trigger ids for keyboard intensity editing. */
  selectedIds: string[];
  lastSelectedId: string | null;

  /** Undo/redo: whole-profile snapshots (edits within 800ms coalesce). */
  undoStack: SongProfile[];
  redoStack: SongProfile[];
  undo: () => void;
  redo: () => void;

  /** Preview-only shift offset (ms) applied visually to all triggers. */
  triggerPreviewOffsetMs: number;
  calibrationTargetsMs: number[];
  /** Engine mode flags mirrored from the WS state message. */
  modes: { analysis: boolean; autoGen: boolean; genreBlend: boolean; recaptureRemaining: number };
  setModes: (m: Partial<{ analysis: boolean; autoGen: boolean; genreBlend: boolean; recaptureRemaining: number }>) => void;

  setTrack: (t: TrackInfo | null) => void;
  setManualUri: (uri: string | null) => void;
  setLiveMode: (v: boolean) => void;
  setAutoWait: (v: boolean) => void;
  setSlot: (id: string) => void;
  setEditingTrigger: (id: string | null) => void;
  setSelection: (ids: string[], last?: string | null) => void;
  setArmedKey: (k: string | null) => void;
  setActivePaletteId: (id: string | null) => void;
  setBlendBrush: (b: 'set' | 'clear' | null) => void;
  setTriggerPreviewOffset: (ms: number) => void;
  setCalibrationTargets: (ms: number[]) => void;

  loadProfile: (p: SongProfile) => void;
  /** All profile edits: immer recipe + debounced whole-profile save. */
  mutateProfile: (fn: (p: SongProfile) => void) => void;
  /** The trigger list being edited (Default or the active slot; lazy-created). */
  workingTriggers: () => MusicTrigger[];
  mutateWorking: (fn: (triggers: MusicTrigger[]) => void) => void;
  flushSave: () => Promise<void>;
}

let saveTimer: ReturnType<typeof setTimeout> | null = null;

const MAX_HISTORY = 10;
/** Edits landing within this window share one undo step (drags, key repeats). */
const HISTORY_COALESCE_MS = 800;
let lastHistoryPushAt = 0;

const snapshot = (p: SongProfile): SongProfile => JSON.parse(JSON.stringify(p)) as SongProfile;

export const useBuilderStore = create<BuilderState>((set, get) => ({
  track: null,
  manualUri: null,
  liveMode: true,
  autoWait: false,
  profile: null,
  dirty: false,
  slotId: '',
  editingTriggerId: null,
  armedKey: null,
  activePaletteId: null,
  blendBrush: null,
  selectedIds: [],
  lastSelectedId: null,
  undoStack: [],
  redoStack: [],
  undo: () => {
    const { profile, undoStack, redoStack } = get();
    if (!profile || !undoStack.length) return;
    set({
      profile: undoStack[undoStack.length - 1],
      undoStack: undoStack.slice(0, -1),
      redoStack: [...redoStack.slice(-(MAX_HISTORY - 1)), snapshot(profile)],
      dirty: true,
    });
    lastHistoryPushAt = 0; // the next edit starts a fresh undo step
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = setTimeout(() => void get().flushSave(), 400);
  },
  redo: () => {
    const { profile, undoStack, redoStack } = get();
    if (!profile || !redoStack.length) return;
    set({
      profile: redoStack[redoStack.length - 1],
      redoStack: redoStack.slice(0, -1),
      undoStack: [...undoStack.slice(-(MAX_HISTORY - 1)), snapshot(profile)],
      dirty: true,
    });
    lastHistoryPushAt = 0;
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = setTimeout(() => void get().flushSave(), 400);
  },

  triggerPreviewOffsetMs: 0,
  calibrationTargetsMs: [],
  modes: { analysis: false, autoGen: false, genreBlend: false, recaptureRemaining: 0 },
  setModes: (m) => set((st) => ({ modes: { ...st.modes, ...m } })),

  setTrack: (t) => set({ track: t }),
  setManualUri: (uri) => set({ manualUri: uri }),
  setLiveMode: (v) => set({ liveMode: v, ...(v ? { manualUri: null } : {}) }),
  setAutoWait: (v) => set({ autoWait: v }),
  setSlot: (id) => set({ slotId: id }),
  setEditingTrigger: (id) => set({ editingTriggerId: id }),
  setSelection: (ids, last) =>
    set({ selectedIds: ids, lastSelectedId: last !== undefined ? last : ids[ids.length - 1] ?? null }),
  setArmedKey: (k) => set({ armedKey: k }),
  setActivePaletteId: (id) => set({ activePaletteId: id }),
  setBlendBrush: (b) => set({ blendBrush: b }),
  setTriggerPreviewOffset: (ms) => set({ triggerPreviewOffsetMs: ms }),
  setCalibrationTargets: (ms) => set({ calibrationTargetsMs: ms }),

  loadProfile: (p) => {
    if (saveTimer) {
      clearTimeout(saveTimer);
      saveTimer = null;
    }
    // History survives post-save refetches of the same song; a song change
    // starts clean.
    const sameSong = get().profile?.spotify_uri === p.spotify_uri;
    set({
      profile: snapshot(p),
      dirty: false,
      ...(sameSong ? {} : { undoStack: [], redoStack: [] }),
    });
  },

  mutateProfile: (fn) => {
    const { profile, undoStack } = get();
    if (!profile) return;
    const now = Date.now();
    const pushHistory = now - lastHistoryPushAt > HISTORY_COALESCE_MS;
    if (pushHistory) lastHistoryPushAt = now;
    set({
      profile: produce(profile, fn),
      dirty: true,
      redoStack: [],
      ...(pushHistory
        ? { undoStack: [...undoStack.slice(-(MAX_HISTORY - 1)), snapshot(profile)] }
        : {}),
    });
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = setTimeout(() => void get().flushSave(), 400);
  },

  workingTriggers: () => {
    const { profile, slotId } = get();
    if (!profile) return [];
    if (slotId) return profile.setlist_triggers[slotId] ?? profile.triggers;
    return profile.triggers;
  },

  mutateWorking: (fn) => {
    const { slotId } = get();
    get().mutateProfile((p) => {
      if (slotId) {
        // Lazy-create the slot override from the Default list (classic behavior).
        if (!p.setlist_triggers[slotId]) {
          p.setlist_triggers[slotId] = JSON.parse(JSON.stringify(p.triggers));
        }
        fn(p.setlist_triggers[slotId]);
      } else {
        fn(p.triggers);
      }
    });
  },

  flushSave: async () => {
    const { profile, dirty } = get();
    if (!profile || !dirty) return;
    if (saveTimer) {
      clearTimeout(saveTimer);
      saveTimer = null;
    }
    set({ dirty: false });
    try {
      await apiPost('/profiles', profile);
    } catch (e) {
      set({ dirty: true }); // retried on next mutation
      console.error('profile save failed', e);
    }
  },
}));

// Warn on close with unsaved changes.
if (typeof window !== 'undefined') {
  window.addEventListener('beforeunload', (e) => {
    if (useBuilderStore.getState().dirty) {
      void useBuilderStore.getState().flushSave();
      e.preventDefault();
    }
  });
}
