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
import type { LibrosaSection } from '../timeline/types';
import { PHASE_COLOR } from '../timeline/dropSequences';

export type UpcomingKind =
  | 'scene' | 'flare' | 'colour' | 'charge' | 'lull' | 'drop' | 'high' | 'low';

export interface UpcomingEvent {
  ms: number;
  kind: UpcomingKind;
  rank: number | null;
  rank_of: number | null;
  source: string;
  num?: number;
  /** a drop only: the moment it actually FIRES (mark + drop timing,
   * spectra/api/upcoming.py) — what the next-event box counts to; `ms` stays
   * the mark, where its marker is drawn */
  fire_ms?: number;
}

/** When an event fires: a drop's `fire_ms`, everything else its `ms`. */
export function eventFireMs(e: Pick<UpcomingEvent, 'ms' | 'fire_ms'>): number {
  return e.fire_ms ?? e.ms;
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

/** Countdown to a tenth of a second — "12.4s" and "99.9s", then plain
 * "1:40" above that. THE MOCKUP'S OWN `cd()` RULE, boundary included
 * (design-fidelity pass, 2026-10-14): tenths right up to 99.95s and none
 * after, which is what makes "99.9s" the widest string the box can ever
 * hold and therefore what its own fixed `4.4ch` count field is sized for.
 * The first build switched to m:ss at 60s and kept a tenth after it
 * ("1:04.2"), which is both wider than the field and a digit that
 * changes ten times a second for minutes on end. Never negative. */
export function fmtCountdown(ms: number): string {
  const { value, unit } = countdownParts(ms);
  return unit ? `${value}${unit}` : value;
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


export const KIND_COLOR: Record<UpcomingKind, string> = {
  scene: '#22d3ee', flare: '#a3e635', colour: '#c084fc',
  charge: PHASE_COLOR.charge, lull: PHASE_COLOR.lull, drop: PHASE_COLOR.drop,
  high: '#f5f5f4', low: '#818cf8',
};

/** The first event that FIRES strictly after `nowMs` (`eventFireMs`: a drop
 * counts to the moment it fires, not its mark — his Q4) — events are assumed
 * sorted ascending (the API's own contract), but this defends against an
 * unsorted/empty list anyway. null when nothing is left this song. */
export function pickNext(events: UpcomingEvent[], nowMs: number): UpcomingEvent | null {
  let best: UpcomingEvent | null = null;
  for (const e of events) {
    const at = eventFireMs(e);
    if (at > nowMs && (best === null || at < eventFireMs(best))) best = e;
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

/* ═══════════════════════════════════════════════════════════════════════
 * THE TRACK'S OWN DRAWING (design-fidelity pass, 2026-10-14)
 *
 * The approved mockup draws the 39px track as an INSET ROUNDED PANEL with
 * four layers under its markers — audit T3, where the live strip was "a
 * bare SVG on the gradient row". Every geometry constant below is the
 * mockup's own (`buildTrack` in data/ui-layout-plan/explainer-final.html);
 * re-lift from there rather than redrawing by eye. All of it is pure so
 * `scripts/check_ui_fidelity.py` can assert the shapes with no browser.
 * ═══════════════════════════════════════════════════════════════════════ */

/** The track's own fixed height, in CSS px and in viewBox units — the
 * two are kept equal on purpose, since the viewBox is 1:1 with the
 * rendered pixels (see `trackX`'s docstring). */
export const TRACK_HEIGHT = 39;
/** The mockup's own horizontal inset, so a marker at 0:00 or at the end
 * is not half-clipped by the panel's own rounded corner. */
export const TRACK_PAD = 8;
/** Marker row centre; the drop band's own top; the terrain's own ceiling. */
export const MARKER_CY = 17;
export const DROP_BAND_Y = 29;
export const TERRAIN_HEIGHT = 14;

/** The inset panel itself (`.sp` surface2 on border, radius 6). */
export const TRACK_FILL = 'var(--surface2)';
export const TRACK_STROKE = 'var(--border)';
/** The played portion's purple wash, and the terrain's fainter one — both
 * the mockup's own literal rgba values (its own `--accent` at 17% / 10%). */
export const PLAYED_TINT = 'rgba(168,85,247,0.17)';
export const TERRAIN_FILL = 'rgba(168,85,247,0.10)';

/** THE TRACK'S VIEWBOX IS 1:1 WITH ITS RENDERED PIXELS, which is what the
 * approved mockup does (`buildTrack` measures `el.clientWidth` and emits
 * `viewBox="0 0 w 39"`), and what every helper below assumes: an x is a
 * pixel, a y is a pixel, a circle is a circle. The strip's FIRST build
 * instead pinned `viewBox="0 0 100 39"` with `preserveAspectRatio="none"`
 * and positioned markers with `%` strings, which stretched every SIZE by
 * the x/y ratio — his own "the little icons on the top timeline are
 * stretched really wide" report, patched then by dividing each size by a
 * measured per-axis scale. A 1:1 viewBox removes the stretch at its
 * source, and it is also the only way to draw the
 * mockup's own mixed geometry (a pill offset half its own width from a
 * timestamp, a triangular flag head) at all — an SVG geometry attribute
 * takes no `calc()`.
 *
 * `x` for a timestamp, in those pixels, inside the panel's own padding so
 * a marker at 0:00 or at the song's end is not half-clipped by the
 * rounded corner. */
export function trackX(ms: number, durationMs: number, widthPx: number): number {
  const f = xFraction(ms, durationMs);
  return TRACK_PAD + f * Math.max(0, widthPx - 2 * TRACK_PAD);
}

/** THE ENERGY TERRAIN (approved idea 4) — a faint step profile of the
 * song's own section energies behind the markers, so the shape of the
 * song is legible at a glance even with nothing playing yet. Real
 * measured data: librosa's own per-section `energy_rms`
 * (`useLibrosa(uri)`, already cached app-wide by the Timeline/debug
 * pages), never a synthesised curve and never re-derived from a marker's
 * RANK — rank orders a boundary's energy CHANGE, which is a different
 * quantity (see spectra/services/midsong_generator.py's own planner).
 *
 * Returns an SVG path `d` in the track's own pixel space, or null when
 * the song has no section analysis — in which case the strip draws no
 * terrain rather than inventing one. */
export function terrainPath(
  sections: LibrosaSection[] | null | undefined,
  durationMs: number,
  widthPx: number,
  heightPx: number = TRACK_HEIGHT,
): string | null {
  if (!sections || sections.length === 0 || durationMs <= 0 || widthPx <= 0) return null;
  const k = heightPx / TRACK_HEIGHT;
  const x = (ms: number) => trackX(ms, durationMs, widthPx).toFixed(2);
  const floorY = ((TRACK_HEIGHT - 1) * k).toFixed(2);
  const yFor = (energy: number) => {
    const level = Math.max(0.15, Math.min(1, energy));
    return (((TRACK_HEIGHT - 2) - level * TERRAIN_HEIGHT) * k).toFixed(2);
  };
  let d = `M${x(0)} ${floorY}`;
  for (const sec of sections) {
    const y = yFor(sec.energy_rms);
    d += ` L${x(sec.start_ms)} ${y} L${x(Math.min(sec.end_ms, durationMs))} ${y}`;
  }
  d += ` L${x(durationMs)} ${floorY}Z`;
  return d;
}

/** One drop sequence as the mockup draws it: a gold CHARGE bar running to
 * the lull, a sky LULL bar running to the drop, and a pink numbered DROP
 * pill on the mark (audit T3 — the live strip drew each member as a tiny
 * separate dot with no badge). Grouped by the sequence's own `num`, which
 * is what `/api/upcoming` already carries per member; a member with no
 * `num` (older data) is its own band so it is never silently dropped. */
export interface DropBand {
  key: string;
  num: number | null;
  chargeMs: number | null;
  lullMs: number | null;
  dropMs: number | null;
}

export function dropBands(events: UpcomingEvent[]): DropBand[] {
  const byNum = new Map<string, DropBand>();
  for (const e of events) {
    if (e.kind !== 'charge' && e.kind !== 'lull' && e.kind !== 'drop') continue;
    const key = e.num != null ? `n${e.num}` : `${e.kind}@${e.ms}`;
    let band = byNum.get(key);
    if (!band) {
      band = { key, num: e.num ?? null, chargeMs: null, lullMs: null, dropMs: null };
      byNum.set(key, band);
    }
    if (e.kind === 'charge') band.chargeMs = e.ms;
    else if (e.kind === 'lull') band.lullMs = e.ms;
    else band.dropMs = e.ms;
  }
  return [...byNum.values()].sort((a, b) => (
    (a.chargeMs ?? a.lullMs ?? a.dropMs ?? 0) - (b.chargeMs ?? b.lullMs ?? b.dropMs ?? 0)
  ));
}

/** Where the "it is next" ring sits vertically for each event kind — the
 * mockup's own three rows: flags at the top edge, scenes/flares on the
 * marker row, drop members in the bottom band. */
export function ringCy(kind: UpcomingKind): number {
  if (kind === 'high' || kind === 'low') return 5;
  if (kind === 'charge' || kind === 'lull' || kind === 'drop') return 32;
  return MARKER_CY;
}

/** The countdown split into its number and its unit, so the unit can be
 * drawn as the mockup's own smaller, muted `<small>` rather than being
 * part of the bold figure (audit T4). See `fmtCountdown` for the
 * boundary rule. */
export function countdownParts(ms: number): { value: string; unit: string | null } {
  const t = Math.max(0, ms) / 1000;
  if (t < 99.95) return { value: t.toFixed(1), unit: 's' };
  const m = Math.floor(t / 60);
  const sec = Math.floor(t - m * 60);
  return { value: `${m}:${String(sec).padStart(2, '0')}`, unit: null };
}

/** THE NEXT-EVENT BOX'S OWN TYPE GLYPH IS THE MARKER SHAPE, FILLED —
 * the mockup's own `kindIcon()` (design-fidelity pass, 2026-10-14): a
 * cyan square for a scene, a lime circle for a flare, a gold wedge for a
 * charge, two sky bars for a lull, a pink pill carrying the drop's own
 * NUMBER, a white up-triangle for High and an indigo down-triangle for
 * Low. The first build drew a muted stroke icon from the shared registry
 * instead, which reads as a generic chip rather than "the thing on the
 * track that is about to fire" (audit T4).
 *
 * Returns SVG markup for a `viewBox="0 0 16 16"` element, so the caller's
 * rAF loop can swap it with one `innerHTML` write and no React render. */
export function kindGlyphSvg(kind: UpcomingKind, num?: number | null): string {
  const c = KIND_COLOR[kind];
  switch (kind) {
    case 'scene':
      return `<rect x="2" y="2" width="12" height="12" rx="2.5" fill="${c}"/>`;
    case 'flare':
      return `<circle cx="8" cy="8" r="5.5" fill="${c}"/>`;
    case 'charge':
      return `<path d="M2 13L14 3V13Z" fill="${c}"/>`;
    case 'lull':
      return `<rect x="3" y="3" width="3.4" height="10" rx="1" fill="${c}"/>`
        + `<rect x="9.6" y="3" width="3.4" height="10" rx="1" fill="${c}"/>`;
    case 'drop':
      return `<rect x="3" y="1.5" width="10" height="13" rx="5" fill="${c}"/>`
        + (num != null
          ? `<text x="8" y="11.2" font-size="8.5" font-weight="800" text-anchor="middle"`
            + ` fill="#14061f" font-family="inherit">${num}</text>`
          : '');
    case 'high':
      return `<path d="M8 2L14 12H2Z" fill="${c}"/>`;
    case 'low':
      return `<path d="M8 14L2 4H14Z" fill="${c}"/>`;
    default:
      return '';
  }
}
