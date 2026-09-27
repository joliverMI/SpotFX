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
    ...plan.scene_changes.map((e) => ({ ms: at(e), kind: 'scene' as const })),
    ...plan.flares.map((e) => ({ ms: at(e), kind: 'flare' as const })),
  ].sort((a, b) => a.ms - b.ms);
}

/** Timeline (Builder) page placement — raw song time, no clock shift.
 * See the module docstring above for why this differs from `plannedMarkers`. */
export function songPositionMarkers(plan: AnalysedPlan | null | undefined): PlannedEventMarker[] {
  if (!plan || !plan.applies) return [];
  return [
    ...plan.scene_changes.map((e) => ({ ms: e.timestamp_ms, kind: 'scene' as const })),
    ...plan.flares.map((e) => ({ ms: e.timestamp_ms, kind: 'flare' as const })),
  ].sort((a, b) => a.ms - b.ms);
}

export const SCENE_MARKER_COLOR = '#22d3ee';
export const FLARE_MARKER_COLOR = '#fbbf24';
