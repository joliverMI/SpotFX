/** THE GLOBAL SONG TIMELINE (song-layout-plan, data/ui-layout-plan/
 * report.md §4): a 39 px, READ-ONLY strip between the menu and the top
 * bar, on every page except Home (its own editable copy) and the
 * Timeline page (its own full toolset) — §13 decision 5.
 *
 * Markers are static SVG, rebuilt only when the song or its plan changes
 * (react-query already invalidates on its own cadence); the playhead and
 * the next-event countdown move in ONE rAF loop that writes attributes/
 * textContent directly — never a React render per frame (report §4.2).
 * Both read the ONE show clock (lib/showClock.ts) — the exact moment the
 * trigger poll fires against, not raw Spotify progress. */
import { useEffect, useRef } from 'react';
import { ICONS } from './iconRegistry';
import {
  eventLabel, FINAL_STRETCH_MS, fmtCountdown, fmtMMSS, KIND_COLOR, KIND_ICON,
  markerOpacity, markerSizePx, NEXT_EVENT_BOX_WIDTH, pickNext, xFraction,
} from './songStrip';
import { useEngineStatus, useUpcoming } from '../queries';
import { getPositionMs, getShowClockMs } from '../lib/showClock';

const TRACK_H = 39;

export default function SongStrip() {
  const { data: status } = useEngineStatus();
  const track = status?.bridge.track ?? null;
  const uri = track?.uri ?? null;
  const { data: upcoming } = useUpcoming(uri);
  const events = upcoming?.events ?? [];
  const durationMs = track?.duration_ms ?? 0;

  const markersGroupRef = useRef<SVGGElement>(null);
  const playheadRef = useRef<SVGLineElement>(null);
  const timeRef = useRef<HTMLSpanElement>(null);
  const nextIconPathRef = useRef<SVGPathElement>(null);
  const nextFillRef = useRef<HTMLDivElement>(null);
  const nextCountRef = useRef<HTMLSpanElement>(null);
  const nextBoxRef = useRef<HTMLDivElement>(null);
  const flashedKeyRef = useRef<string | null>(null);
  const lastNextKindRef = useRef<string | null>(null);

  // Re-render SVG markers only when the inputs that decide WHAT is drawn
  // change (song, its plan) — the per-frame loop below only ever moves
  // the playhead / next-event text, never touches these nodes.
  useEffect(() => {
    const svg = markersGroupRef.current;
    if (!svg) return;
    while (svg.lastChild) svg.removeChild(svg.lastChild);
    const ns = 'http://www.w3.org/2000/svg';
    for (const e of events) {
      if (durationMs <= 0) continue;
      const frac = xFraction(e.ms, durationMs);
      const color = KIND_COLOR[e.kind];
      if (e.kind === 'scene') {
        const r = markerSizePx('scene', e.rank, e.rank_of);
        const rect = document.createElementNS(ns, 'rect');
        rect.setAttribute('x', `${frac * 100 - (r / 3.9)}%`);
        rect.setAttribute('y', '15');
        rect.setAttribute('width', `${r * 2}`);
        rect.setAttribute('height', `${r * 2}`);
        rect.setAttribute('fill', color);
        rect.setAttribute('opacity', String(markerOpacity(e.rank, e.rank_of)));
        svg.appendChild(rect);
      } else if (e.kind === 'flare') {
        const r = markerSizePx('flare', e.rank, e.rank_of);
        const circ = document.createElementNS(ns, 'circle');
        circ.setAttribute('cx', `${frac * 100}%`);
        circ.setAttribute('cy', '19');
        circ.setAttribute('r', `${r}`);
        circ.setAttribute('fill', color);
        circ.setAttribute('opacity', String(markerOpacity(e.rank, e.rank_of)));
        svg.appendChild(circ);
      } else if (e.kind === 'charge' || e.kind === 'lull' || e.kind === 'drop') {
        const bar = document.createElementNS(ns, 'rect');
        bar.setAttribute('x', `${frac * 100}%`);
        bar.setAttribute('y', '29');
        bar.setAttribute('width', e.kind === 'drop' ? '4' : '10');
        bar.setAttribute('height', '6');
        bar.setAttribute('rx', '2');
        bar.setAttribute('fill', color);
        svg.appendChild(bar);
      } else if (e.kind === 'high' || e.kind === 'low') {
        const flag = document.createElementNS(ns, 'line');
        flag.setAttribute('x1', `${frac * 100}%`);
        flag.setAttribute('x2', `${frac * 100}%`);
        flag.setAttribute('y1', '0');
        flag.setAttribute('y2', '8');
        flag.setAttribute('stroke', color);
        flag.setAttribute('stroke-width', '2');
        svg.appendChild(flag);
      }
    }
  }, [events, durationMs]);

  // THE ONE rAF LOOP — playhead, next-event countdown/fill, the one-shot
  // "it just fired" flash. No React state anywhere in here.
  useEffect(() => {
    let raf = 0;
    const tick = () => {
      const now = getShowClockMs();
      const pos = getPositionMs();
      if (playheadRef.current && now != null && durationMs > 0) {
        playheadRef.current.setAttribute('x1', `${xFraction(now, durationMs) * 100}%`);
        playheadRef.current.setAttribute('x2', `${xFraction(now, durationMs) * 100}%`);
      }
      if (timeRef.current) {
        timeRef.current.textContent = pos != null && durationMs > 0
          ? `${fmtMMSS(pos)} / ${fmtMMSS(durationMs)}` : '—:— / —:—';
      }
      const next = now != null ? pickNext(events, now) : null;
      if (next) {
        const remaining = next.ms - (now as number);
        const key = `${next.ms}:${next.kind}`;
        if (nextIconPathRef.current && lastNextKindRef.current !== next.kind) {
          lastNextKindRef.current = next.kind;
          nextIconPathRef.current.setAttribute('d', ICONS[KIND_ICON[next.kind]]);
          nextIconPathRef.current.setAttribute('stroke', KIND_COLOR[next.kind]);
        }
        if (nextCountRef.current) nextCountRef.current.textContent = fmtCountdown(remaining);
        if (nextBoxRef.current) nextBoxRef.current.title = eventLabel(next);
        const soon = remaining <= FINAL_STRETCH_MS;
        if (nextFillRef.current) {
          nextFillRef.current.style.transform =
            `scaleX(${soon ? 1 - remaining / FINAL_STRETCH_MS : 0})`;
        }
        nextBoxRef.current?.classList.toggle('song-strip-next-soon', soon);
        if (remaining <= 0 && flashedKeyRef.current !== key) {
          flashedKeyRef.current = key;
          nextBoxRef.current?.classList.add('song-strip-next-flash');
          setTimeout(() => nextBoxRef.current?.classList.remove('song-strip-next-flash'), 600);
        }
      } else {
        if (nextCountRef.current) nextCountRef.current.textContent = '—';
        if (nextBoxRef.current) { nextBoxRef.current.title = 'Nothing left this song'; }
        if (nextFillRef.current) nextFillRef.current.style.transform = 'scaleX(0)';
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [events, durationMs]);

  if (!track) return null;

  return (
    <div className="song-strip" role="img" aria-label={`${track.title ?? 'Unknown song'} — ${track.artist ?? ''}`}>
      <div className="song-strip-song" title={track.title ?? ''}>
        <span className="song-strip-song-title">{track.title || 'No song'}</span>
        <span className="song-strip-song-artist">{track.artist || ''}</span>
      </div>
      <div className="song-strip-track" style={{ height: TRACK_H }}>
        <svg className="song-strip-svg" preserveAspectRatio="none" viewBox="0 0 100 39">
          <g ref={markersGroupRef} />
          <line ref={playheadRef} x1="0" x2="0" y1="0" y2="39" className="song-strip-playhead" />
        </svg>
      </div>
      <div ref={nextBoxRef} className="song-strip-next" style={{ width: NEXT_EVENT_BOX_WIDTH }}>
        <div ref={nextFillRef} className="song-strip-next-fill" />
        <svg viewBox="0 0 24 24" width={16} height={16} fill="none" stroke="currentColor"
            strokeWidth={2} strokeLinecap="round" strokeLinejoin="round"
            className="song-strip-next-icon" aria-hidden="true">
          <path ref={nextIconPathRef} d="" />
        </svg>
        <span ref={nextCountRef} className="song-strip-next-count tabular-nums">—</span>
      </div>
      <span ref={timeRef} className="song-strip-time tabular-nums">—:— / —:—</span>
    </div>
  );
}
