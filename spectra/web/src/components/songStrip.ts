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
