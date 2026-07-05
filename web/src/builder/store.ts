import { create } from 'zustand';
import { produce, setAutoFreeze } from 'immer';
import { apiPost } from '../api/client';
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

  /** Preview-only shift offset (ms) applied visually to all triggers. */
  triggerPreviewOffsetMs: number;
  calibrationTargetsMs: number[];

  setTrack: (t: TrackInfo | null) => void;
  setManualUri: (uri: string | null) => void;
  setLiveMode: (v: boolean) => void;
  setAutoWait: (v: boolean) => void;
  setSlot: (id: string) => void;
  setEditingTrigger: (id: string | null) => void;
  setArmedKey: (k: string | null) => void;
  setActivePaletteId: (id: string | null) => void;
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
  triggerPreviewOffsetMs: 0,
  calibrationTargetsMs: [],

  setTrack: (t) => set({ track: t }),
  setManualUri: (uri) => set({ manualUri: uri }),
  setLiveMode: (v) => set({ liveMode: v, ...(v ? { manualUri: null } : {}) }),
  setAutoWait: (v) => set({ autoWait: v }),
  setSlot: (id) => set({ slotId: id }),
  setEditingTrigger: (id) => set({ editingTriggerId: id }),
  setArmedKey: (k) => set({ armedKey: k }),
  setActivePaletteId: (id) => set({ activePaletteId: id }),
  setTriggerPreviewOffset: (ms) => set({ triggerPreviewOffsetMs: ms }),
  setCalibrationTargets: (ms) => set({ calibrationTargetsMs: ms }),

  loadProfile: (p) => {
    if (saveTimer) {
      clearTimeout(saveTimer);
      saveTimer = null;
    }
    set({ profile: JSON.parse(JSON.stringify(p)) as SongProfile, dirty: false });
  },

  mutateProfile: (fn) => {
    const { profile } = get();
    if (!profile) return;
    set({ profile: produce(profile, fn), dirty: true });
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
