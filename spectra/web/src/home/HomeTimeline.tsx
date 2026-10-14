/** Home's EDITABLE copy of the global song timeline (song-layout-plan,
 * data/ui-layout-plan/report.md §5): icon toggles for which marker kinds
 * draw, a draggable/zoomable WINDOW (reusing timeline/hooks/useFollowWindow
 * — the SAME follow/manual-window mechanics the Timeline page's own
 * TimelineBar uses, via its own pointer handlers here since TimelineBar
 * itself is bound to the legacy MusicTrigger/EventOption editor model),
 * and a tuned audio-shape trace below it sharing the identical window and
 * playhead.
 *
 * ONE SONG-TIME AXIS: both the strip and the audio shape draw against raw
 * song time (the same convention songPositionMarkers already uses, per
 * debug/plannedEvents.ts's own docstring) — the shape's own stored
 * timestamps are WAV-time, so each sample is shifted by the song's own
 * `timestamp_offset_ms` (its stored shape offset) before drawing, putting
 * the shape on the SAME axis the strip's markers already use. Both
 * playheads read the ONE show clock (lib/showClock.ts). This is a
 * narrower reconciliation than the Timeline/debug pages' own
 * audio_latency_ms-involving math (BuilderPage.tsx, commit note on that
 * page) — deliberately: Home's shape is a glance-and-navigate view, not
 * an editing surface, so it does not need that capture-alignment term at
 * all, only the shape offset that puts it on the right axis.
 *
 * RESPONSIVENESS (the Admiral, 2026-10-14: "the audio shape isn't as
 * responsive"). Measured before the fix: the shape canvas's trace+resize
 * used to live in a React `useEffect` keyed on `[shape, offsetMs, win]` —
 * and `useFollowWindow`'s returned object is a FRESH literal every render
 * (only its `getWin` property is stable), so that effect reran on every
 * parent re-render (the 3s engine-status poll this page's data flows
 * through) AND on every single pointermove of a window drag (each move
 * calls a `useFollowWindow` state setter), each time doing a full
 * `canvas.width = …` resize (a forced clear/realloc) plus a full trace
 * redraw — never rAF-paced, so a drag's redraw landed whenever React next
 * flushed rather than once per frame. The strip's own marker-SVG rebuild
 * had the same shape: its deps included every `win.*` field even though a
 * marker's x position never depends on the window, so dragging rebuilt
 * dozens of SVG nodes on every move for no visual reason. Both are now
 * decoupled: markers (SVG + the shape canvas's own overlay, below) rebuild
 * ONLY on `[shown, durationMs]`; the window-overlay rect, both playheads,
 * the time readout, AND the shape canvas (trace + its own marker overlay)
 * all move into the ONE rAF loop below, reading the window/shape/events
 * via refs — matching SongStrip.tsx's "no React render per frame" rule,
 * and the shared TimelineCanvas.tsx's own DPR-aware "resize only when the
 * measured size actually changed" guard. */
import { useEffect, useMemo, useRef, useState } from 'react';
import HelpLink from '../help/HelpLink';
import IconToggle from '../components/IconToggle';
import {
  axisScale, compensate, drawShapeMarkers, eventLabel, fmtCountdown, fmtMMSS, KIND_COLOR,
  markerOpacity, markerSizePx, pickNext, xFraction,
  type UpcomingEvent,
} from '../components/songStrip';
import { useAudioShapeData, useAudioShapeMeta } from '../timeline/queries';
import { useFollowWindow } from '../timeline/hooks/useFollowWindow';
import { getPositionMs, getShowClockMs } from '../lib/showClock';

type KindFilter = { analysed: boolean; drop: boolean; lightShow: boolean };
const isAnalysed = (k: UpcomingEvent['kind']) => k === 'scene' || k === 'flare' || k === 'colour';
const isDrop = (k: UpcomingEvent['kind']) => k === 'charge' || k === 'lull' || k === 'drop';
const isLightShow = (k: UpcomingEvent['kind']) => k === 'high' || k === 'low';

export default function HomeTimeline({
  uri, title, artist, durationMs, events, showAudioShape = true,
}: {
  uri: string | null;
  title: string;
  artist: string;
  durationMs: number;
  events: UpcomingEvent[];
  /** The kiosk view's own small-screen rule (kiosk/kioskConfig.ts): drop
   * the audio shape rather than squeeze it illegible. */
  showAudioShape?: boolean;
}) {
  const { data: meta } = useAudioShapeMeta(showAudioShape ? uri : null);
  const { data: shape } = useAudioShapeData(showAudioShape ? uri : null, true);
  const offsetMs = Number(meta?.timestamp_offset_ms ?? 0);

  const [filters, setFilters] = useState<KindFilter>({ analysed: true, drop: true, lightShow: true });
  const toggle = (k: keyof KindFilter) => setFilters((f) => ({ ...f, [k]: !f[k] }));

  const shown = useMemo(() => events.filter((e) => (
    (filters.analysed && isAnalysed(e.kind))
    || (filters.drop && isDrop(e.kind))
    || (filters.lightShow && isLightShow(e.kind))
  )), [events, filters]);
  const shownRef = useRef(shown);
  shownRef.current = shown;

  const getNowForWin = useMemo(() => () => getShowClockMs(), []);
  const win = useFollowWindow({ getNowMs: getNowForWin, durationMs: Math.max(1, durationMs), keyPrefix: 'home' });
  // useFollowWindow returns a fresh object every render — only its own
  // `getWin` property is a stable (useCallback-memoized) function. Reading
  // it through a ref, rather than listing `win` in an effect's deps, is
  // what lets the rAF loop below never re-run on an unrelated re-render
  // (see the module docstring's RESPONSIVENESS note).
  const winRef = useRef(win);
  winRef.current = win;
  const shapeRef = useRef(shape);
  shapeRef.current = shape;
  const offsetMsRef = useRef(offsetMs);
  offsetMsRef.current = offsetMs;

  const stripRef = useRef<HTMLDivElement>(null);
  const markersGroupRef = useRef<SVGGElement>(null);
  const windowOverlayRef = useRef<HTMLDivElement>(null);
  const playheadRef = useRef<SVGLineElement>(null);
  const timeRef = useRef<HTMLSpanElement>(null);
  const nextRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const canvasPlayheadRef = useRef<HTMLDivElement>(null);

  // Strip markers: rebuild ONLY when WHAT is drawn changes (the shown
  // events, or the song's own duration) — never on a window move/zoom,
  // since a marker's x position (xFraction against the full song) never
  // depends on the window at all. The window-overlay rect IS window-
  // dependent and moves into the rAF loop below instead, where it's
  // updated every frame rather than on a 500ms timer.
  useEffect(() => {
    const group = markersGroupRef.current;
    const svgEl = group?.closest('svg');
    if (!group || !svgEl) return;
    while (group.lastChild) group.removeChild(group.lastChild);
    // Re-measured every draw (a window/data change) — cheap, and the only
    // way this stays correct across a resize with no ResizeObserver of
    // its own (see songStrip.ts's `axisScale` docstring for why BOTH
    // axes, not just X, need this).
    const svgRect = svgEl.getBoundingClientRect();
    const xScale = axisScale(svgRect.width, 100);
    const yScale = axisScale(svgRect.height, 39);
    const ns = 'http://www.w3.org/2000/svg';
    for (const e of shown) {
      const frac = xFraction(e.ms, durationMs);
      const color = KIND_COLOR[e.kind];
      if (e.kind === 'scene') {
        const r = markerSizePx('scene', e.rank, e.rank_of);
        const widthUnits = compensate(r * 2, xScale);
        const rect = document.createElementNS(ns, 'rect');
        rect.setAttribute('x', `${frac * 100 - widthUnits / 2}%`); rect.setAttribute('y', '15');
        rect.setAttribute('width', `${widthUnits}`); rect.setAttribute('height', `${compensate(r * 2, yScale)}`);
        rect.setAttribute('fill', color); rect.setAttribute('opacity', String(markerOpacity(e.rank, e.rank_of)));
        group.appendChild(rect);
      } else if (e.kind === 'flare') {
        const r = markerSizePx('flare', e.rank, e.rank_of);
        const ell = document.createElementNS(ns, 'ellipse');
        ell.setAttribute('cx', `${frac * 100}%`); ell.setAttribute('cy', '19');
        ell.setAttribute('rx', `${compensate(r, xScale)}`); ell.setAttribute('ry', `${compensate(r, yScale)}`);
        ell.setAttribute('fill', color); ell.setAttribute('opacity', String(markerOpacity(e.rank, e.rank_of)));
        group.appendChild(ell);
      } else if (isDrop(e.kind)) {
        const bar = document.createElementNS(ns, 'rect');
        bar.setAttribute('x', `${frac * 100}%`); bar.setAttribute('y', '29');
        bar.setAttribute('width', `${compensate(e.kind === 'drop' ? 4 : 10, xScale)}`);
        bar.setAttribute('height', `${compensate(6, yScale)}`);
        bar.setAttribute('rx', `${compensate(2, xScale)}`); bar.setAttribute('ry', `${compensate(2, yScale)}`);
        bar.setAttribute('fill', color);
        group.appendChild(bar);
      } else if (isLightShow(e.kind)) {
        // These ARE the Light Show's own High/Low Trigger cues (spectra/
        // api/upcoming.py's own docstring: "The Light Show's High/Low cues
        // (show_cues)...") — drawn as a flag, same shape SongStrip.tsx's
        // own flag branch uses. The check is explicit, not a catch-all
        // `else`, because a catch-all would also match `kind: "colour"`
        // (an authored select_color_set trigger) and wrongly draw it as a
        // Light Show flag — left undrawn here, matching SongStrip.tsx.
        const flag = document.createElementNS(ns, 'line');
        flag.setAttribute('x1', `${frac * 100}%`); flag.setAttribute('x2', `${frac * 100}%`);
        flag.setAttribute('y1', '0'); flag.setAttribute('y2', '8');
        flag.setAttribute('stroke', color);
        flag.setAttribute('stroke-width', `${compensate(2, xScale)}`);
        group.appendChild(flag);
      }
    }
  }, [shown, durationMs]);

  // THE ONE rAF LOOP — the window-overlay rect, both playheads, the time
  // readout, AND the audio-shape canvas (trace + its own marker overlay).
  // No React state anywhere in here: the window/shape/offset/events are
  // all read through refs, so a window drag, a seek, a track change or
  // the 3s engine-status poll are picked up on the very next animation
  // frame rather than waiting on — or forcing — a React re-render.
  useEffect(() => {
    let raf = 0;
    let canvasW = -1, canvasH = -1; // last sized dims — resize only on real change
    const tick = () => {
      const w = winRef.current.getWin();
      const span = Math.max(1, w.endMs - w.startMs);

      if (windowOverlayRef.current) {
        windowOverlayRef.current.style.left = `${(w.startMs / Math.max(1, durationMs)) * 100}%`;
        windowOverlayRef.current.style.width = `${(span / Math.max(1, durationMs)) * 100}%`;
      }

      const canvas = canvasRef.current;
      if (canvas) {
        const dpr = window.devicePixelRatio || 1;
        const cw = canvas.clientWidth, ch = canvas.clientHeight;
        const wantW = Math.round(cw * dpr), wantH = Math.round(ch * dpr);
        if (wantW !== canvasW || wantH !== canvasH) {
          canvas.width = wantW; canvas.height = wantH;
          canvasW = wantW; canvasH = wantH;
        }
        const ctx = canvas.getContext('2d');
        if (ctx && cw > 0 && ch > 0) {
          ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
          ctx.clearRect(0, 0, cw, ch);
          const shape = shapeRef.current;
          const offMs = offsetMsRef.current;
          const xAt = (songMs: number) => ((songMs - w.startMs) / span) * cw;
          if (shape) {
            const drawTrace = (vals: number[], color: string) => {
              ctx.beginPath();
              let started = false;
              for (let i = 0; i < vals.length; i += 1) {
                const songMs = shape.timestamps_ms[i] + offMs;
                if (songMs < w.startMs - 2000 || songMs > w.endMs + 2000) continue;
                const x = xAt(songMs);
                const y = ch - Math.min(1, vals[i]) * ch;
                if (!started) { ctx.moveTo(x, y); started = true; } else ctx.lineTo(x, y);
              }
              ctx.strokeStyle = color; ctx.lineWidth = 1.5; ctx.stroke();
            };
            drawTrace(shape.rms_total, 'rgba(255,255,255,0.55)');
            drawTrace(shape.rms_low, '#fbbf24');
            drawTrace(shape.rms_high, '#a3e635');
          }
          drawShapeMarkers(ctx, shownRef.current, xAt, cw);
        }
      }

      const now = getShowClockMs();
      const pos = getPositionMs();
      if (playheadRef.current && now != null) {
        playheadRef.current.setAttribute('x1', `${xFraction(now, durationMs) * 100}%`);
        playheadRef.current.setAttribute('x2', `${xFraction(now, durationMs) * 100}%`);
      }
      if (canvasPlayheadRef.current && now != null) {
        const frac = Math.min(1, Math.max(0, (now - w.startMs) / span));
        canvasPlayheadRef.current.style.left = `${frac * 100}%`;
        canvasPlayheadRef.current.style.display = now >= w.startMs && now <= w.endMs ? 'block' : 'none';
      }
      if (timeRef.current) {
        timeRef.current.textContent = pos != null && durationMs > 0
          ? `${fmtMMSS(pos)} / ${fmtMMSS(durationMs)}` : '—:— / —:—';
      }
      if (nextRef.current) {
        const n = now != null ? pickNext(shownRef.current, now) : null;
        nextRef.current.textContent = n
          ? `Next: ${eventLabel(n)} in ${fmtCountdown(Math.max(0, n.ms - (now as number)))}` : '';
        nextRef.current.title = n ? eventLabel(n) : '';
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [durationMs]);

  // Window drag — TimelineBar's own dragEdge shape (BuilderPage.tsx's
  // onAdjustFollow convention): in follow mode, an edge drag resizes the
  // look-ahead/window size; a center drag always detaches into a manual
  // pan (the plan's own "dragging leaves Follow" rule).
  const dragWin = (edge: 'start' | 'end' | 'center') => (ev: React.PointerEvent) => {
    ev.preventDefault(); ev.stopPropagation();
    const strip = stripRef.current;
    if (!strip) return;
    (ev.target as HTMLElement).setPointerCapture(ev.pointerId);
    let lastX = ev.clientX;
    const move = (e: PointerEvent) => {
      const rect = strip.getBoundingClientRect();
      const deltaMs = ((e.clientX - lastX) / Math.max(1, rect.width)) * Math.max(1, durationMs);
      lastX = e.clientX;
      if (win.follow && edge !== 'center') {
        if (edge === 'end') win.setFutureS((s) => Math.max(0, s + deltaMs / 1000));
        else win.setWindowS((s) => Math.max(2, s - deltaMs / 1000));
        return;
      }
      const w = win.getWin();
      if (edge === 'center') win.setManualWin({ startMs: w.startMs + deltaMs, endMs: w.endMs + deltaMs });
      else if (edge === 'start') win.setManualWin({ startMs: Math.min(w.startMs + deltaMs, w.endMs - 1000), endMs: w.endMs });
      else win.setManualWin({ startMs: w.startMs, endMs: Math.max(w.endMs + deltaMs, w.startMs + 1000) });
      if (edge === 'center' && win.follow) win.setFollow(false);
    };
    const up = (e: PointerEvent) => {
      (ev.target as HTMLElement).releasePointerCapture(e.pointerId);
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  };

  return (
    <div className="home-timeline card">
      <div className="home-timeline-head">
        <span className="home-timeline-eq" aria-hidden>♪</span>
        <div className="home-timeline-song">
          <span className="song-strip-song-title">{title || 'No song'}</span>
          <span className="song-strip-song-artist">{artist}</span>
        </div>
        <div className="home-timeline-toggles">
          <IconToggle icon="scene" on={filters.analysed} onChange={() => toggle('analysed')} title="Analysed events" />
          <IconToggle icon="pulse" on={filters.drop} onChange={() => toggle('drop')} title="Drop sequences" />
          <IconToggle icon="arrowUp" on={filters.lightShow} onChange={() => toggle('lightShow')} title="Light Show" />
        </div>
        <button type="button" className={`home-timeline-follow${win.follow ? ' on' : ''}`}
          title="Follow the playhead" onClick={() => win.setFollowSnapped(!win.follow)}>⌖</button>
        <button type="button" className="home-timeline-fullsong" title="Full song" onClick={win.fullSong}>↔</button>
        <span ref={timeRef} className="song-strip-time tabular-nums">—:— / —:—</span>
        <HelpLink topic="home-page" title="Help — Home" />
      </div>

      <div ref={stripRef} className="home-timeline-strip">
        <svg className="song-strip-svg" preserveAspectRatio="none" viewBox="0 0 100 39">
          <g ref={markersGroupRef} />
          <line ref={playheadRef} x1="0" x2="0" y1="0" y2="39" className="song-strip-playhead" />
        </svg>
        <div ref={windowOverlayRef} className="home-timeline-window" onPointerDown={dragWin('center')}>
          <div className="home-timeline-window-edge left" onPointerDown={dragWin('start')} />
          <div className="home-timeline-window-edge right" onPointerDown={dragWin('end')} />
        </div>
      </div>

      <div ref={nextRef} className="home-timeline-next" />

      {showAudioShape && (
        <div className="home-timeline-shape">
          <canvas ref={canvasRef} className="home-timeline-shape-canvas" />
          <div ref={canvasPlayheadRef} className="home-timeline-shape-playhead" />
        </div>
      )}
    </div>
  );
}
