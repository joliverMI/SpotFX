/** THE ONE PAINTER for the song track — the inset panel, the energy
 * terrain, the drop sequences' band, the High/Low flags and the rank-sized
 * scene/flare markers (design-fidelity pass, 2026-10-14; audit T3/H3).
 *
 * Both the global read-only strip (SongStrip.tsx) and Home's own editable
 * copy (home/HomeTimeline.tsx) call it, so the two can never disagree
 * about what a marker or a drop sequence looks like — the audit found
 * Home drawing "the same bare SVG as T3" from a second, separate
 * implementation. Every geometry constant is the approved mockup's own
 * (`buildTrack` in data/ui-layout-plan/explainer-final.html); re-lift from
 * there rather than redrawing by eye.
 *
 * It draws into a caller-supplied `<g>` in the SVG's OWN PIXEL SPACE and
 * rewrites the SVG's `viewBox` to match (see songStrip.ts's `trackX`
 * docstring for why 1:1 rather than a stretched `0 0 100 39`), and it
 * returns the drawn marker nodes paired with their timestamps so the
 * caller's rAF loop can fade a passed marker and flash the one that just
 * fired without re-reading the DOM. */
import {
  DROP_BAND_Y, dropBands, KIND_COLOR, MARKER_CY, markerOpacity, markerSizePx, TERRAIN_FILL,
  terrainPath, TRACK_FILL, TRACK_HEIGHT, TRACK_STROKE, trackX, type UpcomingEvent,
} from './songStrip';
import type { LibrosaSection } from '../timeline/types';

const NS = 'http://www.w3.org/2000/svg';

export interface MarkNode { node: SVGElement; ms: number }

export interface PaintTrackInput {
  events: UpcomingEvent[];
  durationMs: number;
  sections: LibrosaSection[] | null | undefined;
}

export function paintTrack(
  svg: SVGSVGElement,
  group: SVGGElement,
  { events, durationMs, sections }: PaintTrackInput,
): MarkNode[] {
  while (group.lastChild) group.removeChild(group.lastChild);
  const marks: MarkNode[] = [];
  const rect = svg.getBoundingClientRect();
  const w = Math.max(1, Math.round(rect.width));
  const h = Math.max(1, Math.round(rect.height)) || TRACK_HEIGHT;
  svg.setAttribute('viewBox', `0 0 ${w} ${h}`);
  const k = h / TRACK_HEIGHT;
  const x = (ms: number) => trackX(ms, durationMs, w);
  const add = <K extends keyof SVGElementTagNameMap>(
    tag: K, attrs: Record<string, string | number>,
  ): SVGElementTagNameMap[K] => {
    const el = document.createElementNS(NS, tag);
    for (const [key, v] of Object.entries(attrs)) el.setAttribute(key, String(v));
    group.appendChild(el);
    return el;
  };

  // 1 — the inset panel.
  add('rect', {
    x: 0.5, y: 0.5, width: w - 1, height: h - 1, rx: 6, ry: 6,
    fill: TRACK_FILL, stroke: TRACK_STROKE, 'stroke-width': 1,
  });

  // 2 — the energy terrain (approved idea 4), behind everything else.
  const d = terrainPath(sections, durationMs, w, h);
  if (d) add('path', { d, fill: TERRAIN_FILL });

  if (durationMs <= 0) return marks;

  // 3 — the drop sequences' own bottom band: gold charge bar → sky lull
  // bar → pink numbered drop pill.
  for (const band of dropBands(events)) {
    const chargeEnd = band.lullMs ?? band.dropMs;
    if (band.chargeMs != null && chargeEnd != null && chargeEnd > band.chargeMs) {
      marks.push({
        node: add('rect', {
          x: x(band.chargeMs), y: DROP_BAND_Y * k,
          width: Math.max(2, x(chargeEnd) - x(band.chargeMs)), height: 6 * k,
          rx: 2, ry: 2, fill: KIND_COLOR.charge, opacity: 0.85,
        }),
        ms: band.chargeMs,
      });
    }
    if (band.lullMs != null && band.dropMs != null && band.dropMs > band.lullMs) {
      marks.push({
        node: add('rect', {
          x: x(band.lullMs), y: DROP_BAND_Y * k,
          width: Math.max(2, x(band.dropMs) - x(band.lullMs)), height: 6 * k,
          rx: 2, ry: 2, fill: KIND_COLOR.lull, opacity: 0.85,
        }),
        ms: band.lullMs,
      });
    }
    if (band.dropMs != null) {
      marks.push({
        node: add('rect', {
          x: x(band.dropMs) - 6, y: (DROP_BAND_Y - 4.5) * k,
          width: 12, height: 14 * k, rx: 6, ry: 6, fill: KIND_COLOR.drop,
        }),
        ms: band.dropMs,
      });
      if (band.num != null) {
        const label = add('text', {
          x: x(band.dropMs), y: (DROP_BAND_Y + 5.6) * k, 'text-anchor': 'middle',
          class: 'song-strip-drop-num', fill: '#14061f',
        });
        label.textContent = String(band.num);
        marks.push({ node: label, ms: band.dropMs });
      }
    }
  }

  // 4 — High/Low flags: a thin stem from the top edge with a triangular
  // head (pointing up for High, down for Low).
  for (const e of events) {
    if (e.kind !== 'high' && e.kind !== 'low') continue;
    const color = KIND_COLOR[e.kind];
    const ex = x(e.ms);
    marks.push({
      node: add('line', {
        x1: ex, x2: ex, y1: 4 * k, y2: (TRACK_HEIGHT - 2) * k,
        stroke: color, 'stroke-width': 1.2, opacity: 0.55,
      }),
      ms: e.ms,
    });
    marks.push({
      node: add('path', {
        fill: color,
        d: e.kind === 'high'
          ? `M${ex - 4.5} ${8 * k} L${ex} ${1 * k} L${ex + 4.5} ${8 * k}Z`
          : `M${ex - 4.5} ${1 * k} L${ex} ${8 * k} L${ex + 4.5} ${1 * k}Z`,
      }),
      ms: e.ms,
    });
  }

  // 5 — scene squares and flare dots, sized/shaded by rank.
  for (const e of events) {
    if (e.kind === 'scene') {
      const r = markerSizePx('scene', e.rank, e.rank_of);
      marks.push({
        node: add('rect', {
          x: x(e.ms) - r, y: MARKER_CY * k - r, width: r * 2, height: r * 2,
          rx: 2, ry: 2, fill: KIND_COLOR.scene, opacity: markerOpacity(e.rank, e.rank_of),
        }),
        ms: e.ms,
      });
    } else if (e.kind === 'flare') {
      const r = markerSizePx('flare', e.rank, e.rank_of);
      marks.push({
        node: add('circle', {
          cx: x(e.ms), cy: MARKER_CY * k, r,
          fill: KIND_COLOR.flare, opacity: markerOpacity(e.rank, e.rank_of),
        }),
        ms: e.ms,
      });
    }
  }
  return marks;
}
