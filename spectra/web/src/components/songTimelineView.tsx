/** THE SONG TIMELINE'S OWN SHARED VIEW STATE — the one window, the one
 * set of marker filters, and the one view-history, shared by the GLOBAL
 * timeline row in the chrome and whatever page is driving it.
 *
 * WHY IT EXISTS (the Admiral, 2026-10-15: "move the timeline below the
 * toolbar ... on the home page, just make sure the audio shape graph is
 * aligned with the timeline"). Home used to draw its OWN copy of the
 * timeline, directly above its audio shape, so the row jumped from the
 * chrome down the page whenever he opened Home. The timeline is now ONE
 * element in the chrome on every route — but Home still edits it (the
 * draggable window sets what its audio shape shows), and Home's card
 * sits inside `<main>`, a DOM sibling of the chrome. A shared store is
 * what lets one element above `<main>` be driven by a card inside it
 * without either one owning the other.
 *
 * THE PROVIDER IS MOUNTED BY `AppChrome`, which also takes the page body
 * as its children — deliberately, so there is exactly ONE mount point
 * and no way for the app, the kiosk and the design-fidelity harness to
 * drift into three (that drift is what PR 426's own docstring records
 * about the chrome ORDER, one layer up).
 *
 * THE WINDOW IS ONLY EDITABLE WHILE SOMETHING IS LISTENING TO IT.
 * `useSongTimelineShape()` registers a listener (Home's audio shape is
 * the only one today); `editable` is true exactly while at least one is
 * registered, which is what keeps the kiosk — where the shape is dropped
 * for space (kiosk/kioskConfig.ts) — from offering a window drag that
 * would move nothing anybody can see.
 *
 * FILTERS ARE THE TIMELINE'S, SET FROM HOME. All three default ON and are
 * deliberately NOT persisted: the toggles live on Home's control row, so
 * a filter left off and then forgotten on another route would be
 * unreachable; a reload always comes back to everything shown.
 *
 * NO PER-FRAME STATE LIVES HERE. The window is read through its own
 * `getWin()` getter (useFollowWindow's own contract) by the rAF loops
 * that draw the strip and the canvas — this context re-renders only when
 * a filter, the follow mode or a committed manual window changes. */
import {
  createContext, useCallback, useContext, useEffect, useMemo, useRef, useState,
} from 'react';
import type { ReactNode } from 'react';
import { useFollowWindow } from '../timeline/hooks/useFollowWindow';
import type { Win } from '../timeline/hooks/useFollowWindow';
import { getShowClockMs } from '../lib/showClock';
import { useEngineStatus } from '../queries';
import type { UpcomingKind } from './songStrip';

export interface KindFilter {
  analysed: boolean;
  drop: boolean;
  lightShow: boolean;
}

/** Which filter governs each event kind the timeline can draw. `colour`
 * rides with the analysed group: it is an authored `select_color_set`
 * trigger, one of the analysed-events family, and the strip deliberately
 * draws no shape for it anyway (songStrip.ts::drawShapeMarkers). */
export function kindShown(kind: UpcomingKind, f: KindFilter): boolean {
  if (kind === 'scene' || kind === 'flare' || kind === 'colour') return f.analysed;
  if (kind === 'charge' || kind === 'lull' || kind === 'drop') return f.drop;
  return f.lightShow;
}

interface Snapshot { startMs: number; endMs: number; follow: boolean }

export interface SongTimelineView {
  /** The shared zoom window — the SAME object shape the Timeline page's
   * own canvas consumes, so `getWin` can be handed straight to it. */
  win: ReturnType<typeof useFollowWindow>;
  durationMs: number;
  filters: KindFilter;
  toggleFilter: (k: keyof KindFilter) => void;
  /** True exactly while something is listening to the window (Home's
   * audio shape) — the strip draws its draggable window overlay only
   * then. */
  editable: boolean;
  /** Push the CURRENT window onto the undo stack. Called by whatever is
   * about to change it (a drag starting, Follow, Full song), so a
   * committed change is one step rather than one per pointermove. */
  pushHistory: () => void;
  undo: () => void;
  redo: () => void;
  canUndo: boolean;
  canRedo: boolean;
  /** Register/unregister a listener — see `useSongTimelineShape`. */
  addShapeOwner: () => () => void;
}

const Ctx = createContext<SongTimelineView | null>(null);

/** The fallback a consumer rendered outside the provider gets: every
 * filter on, nothing editable, a full-song window. Returning this rather
 * than throwing is deliberate — `check_topbar_scene_colour_names.mjs` and
 * friends mount single components in isolation, and a context a test
 * harness must remember to wrap is a gate nobody exercises. */
function useFallback(): SongTimelineView {
  const win = useFollowWindow({ getNowMs: () => null, durationMs: 1, keyPrefix: 'songtl-fallback' });
  return useMemo(() => ({
    win,
    durationMs: 0,
    filters: { analysed: true, drop: true, lightShow: true },
    toggleFilter: () => {},
    editable: false,
    pushHistory: () => {},
    undo: () => {},
    redo: () => {},
    canUndo: false,
    canRedo: false,
    addShapeOwner: () => () => {},
  }), [win]);
}

export function useSongTimelineView(): SongTimelineView {
  const fallback = useFallback();
  return useContext(Ctx) ?? fallback;
}

/** Home's audio shape calls this: while mounted, the strip's window is
 * editable. Ref-counted, so two shapes (there is one today) would both
 * have to go before the overlay disappears. */
export function useSongTimelineShape(active: boolean): void {
  const { addShapeOwner } = useSongTimelineView();
  useEffect(() => {
    if (!active) return undefined;
    return addShapeOwner();
  }, [active, addShapeOwner]);
}

export function SongTimelineViewProvider({ children }: { children: ReactNode }) {
  const { data: status } = useEngineStatus();
  const durationMs = status?.bridge.track?.duration_ms ?? 0;

  const getNow = useMemo(() => () => getShowClockMs(), []);
  const win = useFollowWindow({
    getNowMs: getNow, durationMs: Math.max(1, durationMs), keyPrefix: 'home',
  });
  // `useFollowWindow` returns a fresh object every render (only its own
  // `getWin` is memoized), so everything below reads it through a ref —
  // that is what keeps an unrelated re-render from re-running an effect
  // or invalidating a callback.
  const winRef = useRef(win);
  winRef.current = win;

  const [filters, setFilters] = useState<KindFilter>(
    { analysed: true, drop: true, lightShow: true });
  const toggleFilter = useCallback((k: keyof KindFilter) => {
    setFilters((f) => ({ ...f, [k]: !f[k] }));
  }, []);

  const [owners, setOwners] = useState(0);
  const addShapeOwner = useCallback(() => {
    setOwners((n) => n + 1);
    return () => setOwners((n) => Math.max(0, n - 1));
  }, []);

  const [past, setPast] = useState<Snapshot[]>([]);
  const [future, setFuture] = useState<Snapshot[]>([]);
  const snapshot = useCallback((): Snapshot => {
    const w: Win = winRef.current.getWin();
    return { startMs: w.startMs, endMs: w.endMs, follow: winRef.current.follow };
  }, []);
  const pushHistory = useCallback(() => {
    setPast((p) => [...p.slice(-19), snapshot()]);
    setFuture([]);
  }, [snapshot]);
  const restore = useCallback((s: Snapshot) => {
    const w = winRef.current;
    if (s.follow) w.setFollowSnapped(true);
    else { w.setFollow(false); w.setManualWin({ startMs: s.startMs, endMs: s.endMs }); }
  }, []);
  const undo = useCallback(() => {
    setPast((p) => {
      if (p.length === 0) return p;
      const now = snapshot();
      setFuture((f) => [now, ...f].slice(0, 20));
      restore(p[p.length - 1]);
      return p.slice(0, -1);
    });
  }, [snapshot, restore]);
  const redo = useCallback(() => {
    setFuture((f) => {
      if (f.length === 0) return f;
      const now = snapshot();
      setPast((p) => [...p.slice(-19), now]);
      restore(f[0]);
      return f.slice(1);
    });
  }, [snapshot, restore]);

  const value = useMemo<SongTimelineView>(() => ({
    win,
    durationMs,
    filters,
    toggleFilter,
    editable: owners > 0,
    pushHistory,
    undo,
    redo,
    canUndo: past.length > 0,
    canRedo: future.length > 0,
    addShapeOwner,
  }), [win, durationMs, filters, toggleFilter, owners, pushHistory, undo, redo,
       past.length, future.length, addShapeOwner]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
