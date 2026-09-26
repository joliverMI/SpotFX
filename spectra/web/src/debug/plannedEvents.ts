/** Planned analysed events on the debug page's shape canvas
 * (GET /spectra/api/analysed-plan — spectra/api/analysed_plan.py).
 *
 * Pure, DOM-free, so scripts/check_planned_event_markers.mjs can drive it.
 *
 * WHERE A MARKER GOES. An event at song time T fires when the trigger
 * clock reaches T, and the trigger clock is the bridge's effective
 * position (raw + the xcorr shape offset the bridge applies) plus
 * `showClockShiftMs` (the A/V lead minus River's buffer compensation,
 * served by the API). This canvas's playhead is its own clock:
 * raw + its shape-offset term − audio latency − perception trim
 * (DebugPage's playheadShift). So when the event fires the canvas
 * playhead reads T − showClockShiftMs + (canvasShiftMs − bridgeShapeOffsetMs),
 * and that is where the marker is drawn — the playhead crosses it at the
 * moment it fires. */
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

export const SCENE_MARKER_COLOR = '#22d3ee';
export const FLARE_MARKER_COLOR = '#fbbf24';
