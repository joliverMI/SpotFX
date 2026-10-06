/** Planned analysed events (GET /spectra/api/analysed-plan —
 * spectra/api/analysed_plan.py), shared between the debug page's shape
 * canvas and the Timeline (Builder) page's audio-shape canvas
 * (../timeline/BuilderPage.tsx) — one source of truth for what a marker
 * IS (`AnalysedPlan`, `PlannedEventMarker`, the two marker colours), each
 * page choosing the placement math that matches its own time axis.
 *
 * Pure, DOM-free, so scripts/check_planned_event_markers.mjs and
 * scripts/check_timeline_analysed_markers.mjs can drive them.
 *
 * `timestamp_ms` on every plan entry is already SONG TIME (the
 * stored-trigger convention — see analysed_plan.py's own docstring).
 *
 * DEBUG'S PLACEMENT (`plannedMarkerMs`/`plannedMarkers`) — WHERE A MARKER
 * GOES ON THAT CANVAS. An event at song time T fires when the trigger
 * clock reaches T, and the trigger clock is the bridge's effective
 * position (raw + the xcorr shape offset the bridge applies) plus
 * `showClockShiftMs` (the A/V lead minus River's buffer compensation,
 * served by the API). The debug canvas's playhead is its OWN clock:
 * raw + its shape-offset term − audio latency − perception trim
 * (DebugPage's playheadShift). So when the event fires the canvas
 * playhead reads T − showClockShiftMs + (canvasShiftMs − bridgeShapeOffsetMs),
 * and that is where the marker is drawn — the playhead crosses it at the
 * moment it fires.
 *
 * THE TIMELINE PAGE'S PLACEMENT (`songPositionMarkers`) is simpler and
 * deliberately does NOT apply any of the above: the Timeline canvas's
 * data (RMS bands, triggers, librosa overlays) already draws at raw,
 * un-shifted timestamps — the same song-position convention a stored
 * trigger's own `timestamp_ms` uses (see canvas/layers.ts's `dataX`
 * comment) — so an analysed-plan event's `timestamp_ms` is exactly
 * where it belongs on that axis too. `show_clock_shift_ms` answers "how
 * far ahead of the live playhead is the trigger clock right now", which
 * only matters to a canvas whose X axis IS that live playhead (debug's);
 * it says nothing about where an event sits in the song, so it plays no
 * part here. */
import type { PlannedEventMarker } from '../timeline/canvas/frame';

export interface AnalysedPlanEvent {
  timestamp_ms: number;
  intensity: number;
  /** 1 = the song's strongest section-energy change; null when unranked
   * (a stored cue planned under older settings). Absent from an older API. */
  rank?: number | null;
  rank_of?: number | null;
}

export interface AnalysedPlan {
  uri: string;
  applies: boolean;
  reason: string | null;
  effective_mode: string;
  has_authored: boolean;
  scene_source: 'stored' | 'planned' | null;
  scene_changes: AnalysedPlanEvent[];
  flares: AnalysedPlanEvent[];
  show_clock_shift_ms: number;
  rank_of?: number | null;
  /** THE LIGHT SHOW's High/Low Triggers for this song (spectra/services/
   * show_cues.py; lightshow/types.ts' SongCues). Absent from an older API. */
  show_cues?: import('../lightshow/types').SongCues | null;
}

export function plannedMarkerMs(
  eventMs: number, showClockShiftMs: number, canvasShiftMs: number, bridgeShapeOffsetMs: number,
): number {
  return eventMs - showClockShiftMs + (canvasShiftMs - bridgeShapeOffsetMs);
}

export function plannedMarkers(
  plan: AnalysedPlan | null | undefined, canvasShiftMs: number, bridgeShapeOffsetMs: number,
): PlannedEventMarker[] {
  if (!plan || !plan.applies) return [];
  const at = (e: AnalysedPlanEvent) =>
    plannedMarkerMs(e.timestamp_ms, plan.show_clock_shift_ms ?? 0, canvasShiftMs, bridgeShapeOffsetMs);
  return [
    ...plan.scene_changes.map((e) => ({ ms: at(e), kind: 'scene' as const, ...rankFields(e) })),
    ...plan.flares.map((e) => ({ ms: at(e), kind: 'flare' as const, ...rankFields(e) })),
  ].sort((a, b) => a.ms - b.ms);
}

const rankFields = (e: AnalysedPlanEvent) => ({ rank: e.rank ?? null, rankOf: e.rank_of ?? null });

/** Timeline (Builder) page placement — raw song time, no clock shift.
 * See the module docstring above for why this differs from `plannedMarkers`. */
export function songPositionMarkers(plan: AnalysedPlan | null | undefined): PlannedEventMarker[] {
  if (!plan || !plan.applies) return [];
  return [
    ...plan.scene_changes.map((e) => ({ ms: e.timestamp_ms, kind: 'scene' as const, ...rankFields(e) })),
    ...plan.flares.map((e) => ({ ms: e.timestamp_ms, kind: 'flare' as const, ...rankFields(e) })),
  ].sort((a, b) => a.ms - b.ms);
}

export const SCENE_MARKER_COLOR = '#22d3ee';
/** Lime, NOT gold: gold, sky-blue and magenta belong to the charge, lull
 * and drop phases (drop-detection plan decision 5; timeline/dropSequences.ts
 * PHASE_COLOR). Until 2026-10-06 this was the charge's own gold #fbbf24, so
 * an analysed flare and a charge read as the same thing. */
export const FLARE_MARKER_COLOR = '#a3e635';

/** RANK — how strong a planned moment is among the song's analysed
 * transitions (2026-10-04, data/scene-change-ranking-plan/report.md §4, the
 * Admiral's "subtle rank on the Timeline and debug markers"). `rank` 1 is
 * the song's strongest section-energy change, of `rankOf` ranked moments;
 * null when the API could not rank it (a stored cue planned under settings
 * the current plan no longer produces) — such a marker draws exactly as it
 * did before ranks existed.
 *
 * Two redundant cues, both subtle: the SIZE tier (bottom / middle / top
 * third → the scene tab 6 / 10 / 14 px wide, the flare dot 2.5 / 3.5 /
 * 4.5 px) and the OPACITY (0.45 for the weakest → 0.95 for the strongest,
 * linear in rank). A tooltip names it in words. */
export type RankTier = 0 | 1 | 2;

export function rankFraction(rank: number | null | undefined, rankOf: number | null | undefined): number | null {
  if (!rank || !rankOf || rankOf < 1 || rank < 1) return null;
  if (rankOf === 1) return 1;
  return 1 - (Math.min(rank, rankOf) - 1) / (rankOf - 1);
}

export function rankTier(rank: number | null | undefined, rankOf: number | null | undefined): RankTier | null {
  if (!rank || !rankOf || rankOf < 1 || rank < 1) return null;
  const third = (Math.min(rank, rankOf) - 1) / rankOf; // 0 = strongest
  return third < 1 / 3 ? 2 : third < 2 / 3 ? 1 : 0;
}

export const SCENE_TAB_HALF_WIDTH: Record<RankTier, number> = { 0: 3, 1: 5, 2: 7 };
export const FLARE_DOT_RADIUS: Record<RankTier, number> = { 0: 2.5, 1: 3.5, 2: 4.5 };
export const RANK_OPACITY_MIN = 0.45;
export const RANK_OPACITY_MAX = 0.95;

export function rankOpacity(rank: number | null | undefined, rankOf: number | null | undefined, unranked: number): number {
  const f = rankFraction(rank, rankOf);
  return f == null ? unranked : RANK_OPACITY_MIN + (RANK_OPACITY_MAX - RANK_OPACITY_MIN) * f;
}

export function markerTooltip(m: PlannedEventMarker): string {
  const what = m.kind === 'scene' ? 'scene change' : 'flare';
  if (!m.rank || !m.rankOf) return `${what} · not ranked (planned under older settings)`;
  return `#${m.rank} of ${m.rankOf} · section-energy change · ${what}`;
}
