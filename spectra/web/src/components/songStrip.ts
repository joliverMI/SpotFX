/** Pure, DOM-free helpers for the global song timeline (song-layout-plan,
 * data/ui-layout-plan/report.md §4) and its editable Home copy. Kept
 * out of the React component so `scripts/check_song_strip.mjs` can
 * transpile and drive this module with esbuild, with no DOM — the
 * `debug/plannedEvents.ts` convention.
 *
 * `UpcomingEvent`/`UpcomingResponse` mirror spectra/api/upcoming.py's own
 * wire shape EXACTLY — this is the one source of "what will fire", never
 * re-derived here (AGENTS.md: a countdown promising an event the room
 * will never play is the same lie as a held room reading like a broken
 * one). */
import { rankOpacity, rankTier, SCENE_TAB_HALF_WIDTH, FLARE_DOT_RADIUS } from '../debug/plannedEvents';
import { PHASE_COLOR } from '../timeline/dropSequences';
import type { IconName } from './iconRegistry';

export type UpcomingKind =
  | 'scene' | 'flare' | 'colour' | 'charge' | 'lull' | 'drop' | 'high' | 'low';

export interface UpcomingEvent {
  ms: number;
  kind: UpcomingKind;
  rank: number | null;
  rank_of: number | null;
  source: string;
  num?: number;
}

export interface UpcomingResponse {
  uri: string;
  effective_mode: string;
  has_authored: boolean;
  events: UpcomingEvent[];
}

/** The box flashes/fills inside this many ms of the mark (report §4:
 * "Inside the last 3 seconds the box glows and its background fills"). */
export const FINAL_STRETCH_MS = 3000;

/** Fixed width of the next-event box — big enough for "99.9s" with no
 * resize (report §13 decision, the next-event box edit: 96 px). */
export const NEXT_EVENT_BOX_WIDTH = 96;

export function fmtMMSS(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  const m = Math.floor(s / 60);
  return `${m}:${String(s % 60).padStart(2, '0')}`;
}

/** Countdown to a tenth of a second — "12.4s" under a minute, "1:04.2"
 * over it (report §4's own examples). Never negative. */
export function fmtCountdown(ms: number): string {
  const t = Math.max(0, ms) / 1000;
  if (t < 60) return `${t.toFixed(1)}s`;
  const m = Math.floor(t / 60);
  const rest = t - m * 60;
  return `${m}:${rest.toFixed(1).padStart(4, '0')}`;
}

const KIND_LABEL: Record<UpcomingKind, string> = {
  scene: 'Scene', flare: 'Flare', colour: 'Colour',
  charge: 'Charge', lull: 'Lull', drop: 'Drop',
  high: 'High trigger', low: 'Low trigger',
};

/** "Scene · 7 of 15", "Flare", "Charge · drop 1", "Drop 1", "High trigger"
 * — the next-event box's full label (shown on hover; the box itself
 * shows only the type icon + countdown, decision: no label text in the
 * box). */
export function eventLabel(e: Pick<UpcomingEvent, 'kind' | 'rank' | 'rank_of' | 'num'>): string {
  const base = KIND_LABEL[e.kind];
  if ((e.kind === 'charge' || e.kind === 'lull') && e.num != null) return `${base} · drop ${e.num}`;
  if (e.kind === 'drop' && e.num != null) return `${base} ${e.num}`;
  if (e.kind === 'scene' && e.rank != null && e.rank_of != null) return `${base} · ${e.rank} of ${e.rank_of}`;
  return base;
}

export const KIND_ICON: Record<UpcomingKind, IconName> = {
  scene: 'scene', flare: 'bolt', colour: 'bulb',
  charge: 'pulse', lull: 'pulse', drop: 'pulse',
  high: 'arrowUp', low: 'arrowDown',
};

export const KIND_COLOR: Record<UpcomingKind, string> = {
  scene: '#22d3ee', flare: '#a3e635', colour: '#c084fc',
  charge: PHASE_COLOR.charge, lull: PHASE_COLOR.lull, drop: PHASE_COLOR.drop,
  high: '#f5f5f4', low: '#818cf8',
};

/** The first event strictly ahead of `nowMs` — events are assumed sorted
 * ascending (the API's own contract), but this defends against an
 * unsorted/empty list anyway. null when nothing is left this song. */
export function pickNext(events: UpcomingEvent[], nowMs: number): UpcomingEvent | null {
  let best: UpcomingEvent | null = null;
  for (const e of events) {
    if (e.ms > nowMs && (best === null || e.ms < best.ms)) best = e;
  }
  return best;
}

/** Marker size/radius by rank, reusing the EXACT drawing rule
 * debug/plannedEvents.ts already established, so the global strip, the
 * Timeline strip and the audio shape never disagree about what "strong"
 * looks like. */
export function markerSizePx(kind: 'scene' | 'flare', rank: number | null, rankOf: number | null): number {
  const tier = rankTier(rank, rankOf) ?? 1;
  return kind === 'scene' ? SCENE_TAB_HALF_WIDTH[tier] : FLARE_DOT_RADIUS[tier];
}

export function markerOpacity(rank: number | null, rankOf: number | null): number {
  return rankOpacity(rank, rankOf, 0.7);
}

/** x position (0..1, a fraction of the strip's width) for a timestamp. */
export function xFraction(ms: number, durationMs: number): number {
  if (durationMs <= 0) return 0;
  return Math.min(1, Math.max(0, ms / durationMs));
}

/** Canvas-draw the SAME markers the SVG strip above draws — same shapes,
 * same colours (KIND_COLOR), same rank-driven size/opacity (markerSizePx/
 * markerOpacity) — so the zoomed audio-shape canvas and the full-song
 * strip never disagree about what a scene/flare/drop/light-show marker
 * looks like. `xAt` maps a song-ms timestamp to an absolute canvas-pixel
 * x (the caller's own window mapping); only events whose `xAt` lands
 * inside [0, w] are drawn.
 *
 * `kind: "high"/"low"` ARE the Light Show's own High/Low Trigger cues —
 * not a separate concept this module invents. `spectra/api/upcoming.py`'s
 * own docstring says so verbatim ("The Light Show's High/Low cues
 * (show_cues) — independent of whether analysed events apply, same as the
 * Timeline's own markers"), and its handler appends them with
 * `source: "show_cue"` straight from `plan["show_cues"]`
 * (`spectra/services/show_cues.py`) — the exact store
 * `canvas/lightShowLayer.ts`'s own flag markers on the Timeline page's
 * audio-shape canvas already draw from. So a flag here IS a Light Show
 * trigger marker, drawn the same way SongStrip.tsx's own flag branch
 * draws it, gated by the SAME `isLightShow` toggle HomeTimeline.tsx's
 * filter already uses — no new marker kind, no new data source.
 *
 * The kind check is deliberately EXPLICIT (`'high' || 'low'`), not a
 * catch-all `else` — a catch-all would also match `kind: "colour"`
 * (an authored select_color_set trigger, reachable through
 * `/api/upcoming`'s "his own triggers fire instead" branch) and draw it
 * as a Light Show flag, which it is not. SongStrip.tsx's own flag branch
 * already checks explicitly for this reason; `colour` is deliberately
 * left undrawn here too, matching that established, shipped behaviour,
 * rather than inventing a new shape for it.
 *
 * Pure aside from the passed-in ctx, so
 * scripts/check_home_timeline_light_show_markers.mjs and
 * scripts/check_song_strip.mjs can drive it with a recording fake
 * context — no real <canvas>. */
export function drawShapeMarkers(
  ctx: CanvasRenderingContext2D,
  events: UpcomingEvent[],
  xAt: (ms: number) => number,
  w: number,
): void {
  for (const e of events) {
    const x = xAt(e.ms);
    if (x < -10 || x > w + 10) continue;
    const color = KIND_COLOR[e.kind];
    if (e.kind === 'scene') {
      const r = markerSizePx('scene', e.rank, e.rank_of);
      ctx.globalAlpha = markerOpacity(e.rank, e.rank_of);
      ctx.fillStyle = color;
      ctx.fillRect(x - r, 2, r * 2, r * 2);
    } else if (e.kind === 'flare') {
      const r = markerSizePx('flare', e.rank, e.rank_of);
      ctx.globalAlpha = markerOpacity(e.rank, e.rank_of);
      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.arc(x, 12, r, 0, Math.PI * 2);
      ctx.fill();
    } else if (e.kind === 'charge' || e.kind === 'lull' || e.kind === 'drop') {
      ctx.globalAlpha = 1;
      ctx.fillStyle = color;
      const bw = e.kind === 'drop' ? 4 : 10;
      ctx.fillRect(x - bw / 2, 13, bw, 6);
    } else if (e.kind === 'high' || e.kind === 'low') {
      ctx.globalAlpha = 1;
      ctx.strokeStyle = color;
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, 8);
      ctx.stroke();
    }
    // 'colour' deliberately drawn as nothing — see the docstring above.
  }
  ctx.globalAlpha = 1;
}
