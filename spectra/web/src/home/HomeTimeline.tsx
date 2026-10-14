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
 * all, only the shape offset that puts it on the right axis. */
import { useEffect, useMemo, useRef, useState } from 'react';
import HelpLink from '../help/HelpLink';
import IconToggle from '../components/IconToggle';
import {
  eventLabel, fmtCountdown, fmtMMSS, KIND_COLOR,
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

  const getNowForWin = useMemo(() => () => getShowClockMs(), []);
  const win = useFollowWindow({ getNowMs: getNowForWin, durationMs: Math.max(1, durationMs), keyPrefix: 'home' });

  const stripRef = useRef<HTMLDivElement>(null);
  const markersGroupRef = useRef<SVGGElement>(null);
  const windowOverlayRef = useRef<HTMLDivElement>(null);
  const playheadRef = useRef<SVGLineElement>(null);
  const timeRef = useRef<HTMLSpanElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const canvasPlayheadRef = useRef<HTMLDivElement>(null);

  // Window overlay + markers: redraw whenever the window moves/zooms or
  // the shown events change (cheap — a few dozen DOM nodes).
  useEffect(() => {
    const draw = () => {
      const w = win.getWin();
      const span = Math.max(1, w.endMs - w.startMs);
      if (windowOverlayRef.current) {
        windowOverlayRef.current.style.left = `${(w.startMs / Math.max(1, durationMs)) * 100}%`;
        windowOverlayRef.current.style.width = `${(span / Math.max(1, durationMs)) * 100}%`;
      }
      const svg = markersGroupRef.current;
      if (svg) {
        while (svg.lastChild) svg.removeChild(svg.lastChild);
        const ns = 'http://www.w3.org/2000/svg';
        for (const e of shown) {
          const frac = xFraction(e.ms, durationMs);
          const color = KIND_COLOR[e.kind];
          if (e.kind === 'scene') {
            const r = markerSizePx('scene', e.rank, e.rank_of);
            const rect = document.createElementNS(ns, 'rect');
            rect.setAttribute('x', `${frac * 100}%`); rect.setAttribute('y', '15');
            rect.setAttribute('width', `${r * 2}`); rect.setAttribute('height', `${r * 2}`);
            rect.setAttribute('fill', color); rect.setAttribute('opacity', String(markerOpacity(e.rank, e.rank_of)));
            svg.appendChild(rect);
          } else if (e.kind === 'flare') {
            const r = markerSizePx('flare', e.rank, e.rank_of);
            const circ = document.createElementNS(ns, 'circle');
            circ.setAttribute('cx', `${frac * 100}%`); circ.setAttribute('cy', '19'); circ.setAttribute('r', `${r}`);
            circ.setAttribute('fill', color); circ.setAttribute('opacity', String(markerOpacity(e.rank, e.rank_of)));
            svg.appendChild(circ);
          } else if (isDrop(e.kind)) {
            const bar = document.createElementNS(ns, 'rect');
            bar.setAttribute('x', `${frac * 100}%`); bar.setAttribute('y', '29');
            bar.setAttribute('width', e.kind === 'drop' ? '4' : '10'); bar.setAttribute('height', '6');
            bar.setAttribute('rx', '2'); bar.setAttribute('fill', color);
            svg.appendChild(bar);
          } else {
            const flag = document.createElementNS(ns, 'line');
            flag.setAttribute('x1', `${frac * 100}%`); flag.setAttribute('x2', `${frac * 100}%`);
            flag.setAttribute('y1', '0'); flag.setAttribute('y2', '8');
            flag.setAttribute('stroke', color); flag.setAttribute('stroke-width', '2');
            svg.appendChild(flag);
          }
        }
      }
    };
    draw();
    const id = setInterval(draw, 500); // follow mode's window creeps even with no pointer input
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shown, durationMs, win.follow, win.manualWin, win.windowS, win.futureS]);

  // The audio shape trace, redrawn when the window or the data changes.
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !shape) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const w = canvas.clientWidth, h = canvas.clientHeight;
    canvas.width = w * devicePixelRatio; canvas.height = h * devicePixelRatio;
    ctx.scale(devicePixelRatio, devicePixelRatio);
    ctx.clearRect(0, 0, w, h);
    const win2 = win.getWin();
    const span = Math.max(1, win2.endMs - win2.startMs);
    const xAt = (songMs: number) => ((songMs - win2.startMs) / span) * w;
    const draw = (vals: number[], color: string) => {
      ctx.beginPath();
      let started = false;
      for (let i = 0; i < vals.length; i += 1) {
        const songMs = shape.timestamps_ms[i] + offsetMs;
        if (songMs < win2.startMs - 2000 || songMs > win2.endMs + 2000) continue;
        const x = xAt(songMs);
        const y = h - Math.min(1, vals[i]) * h;
        if (!started) { ctx.moveTo(x, y); started = true; } else ctx.lineTo(x, y);
      }
      ctx.strokeStyle = color; ctx.lineWidth = 1.5; ctx.stroke();
    };
    draw(shape.rms_total, 'rgba(255,255,255,0.55)');
    draw(shape.rms_low, '#fbbf24');
    draw(shape.rms_high, '#a3e635');
  }, [shape, offsetMs, win]);

  // The ONE rAF loop — both playheads + the time readout.
  useEffect(() => {
    let raf = 0;
    const tick = () => {
      const now = getShowClockMs();
      const pos = getPositionMs();
      if (playheadRef.current && now != null) {
        playheadRef.current.setAttribute('x1', `${xFraction(now, durationMs) * 100}%`);
        playheadRef.current.setAttribute('x2', `${xFraction(now, durationMs) * 100}%`);
      }
      if (canvasPlayheadRef.current && now != null) {
        const w = win.getWin();
        const span = Math.max(1, w.endMs - w.startMs);
        const frac = Math.min(1, Math.max(0, (now - w.startMs) / span));
        canvasPlayheadRef.current.style.left = `${frac * 100}%`;
        canvasPlayheadRef.current.style.display = now >= w.startMs && now <= w.endMs ? 'block' : 'none';
      }
      if (timeRef.current) {
        timeRef.current.textContent = pos != null && durationMs > 0
          ? `${fmtMMSS(pos)} / ${fmtMMSS(durationMs)}` : '—:— / —:—';
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [durationMs, win]);

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

  const next = useMemo(() => {
    const now = getShowClockMs();
    return now != null ? pickNext(shown, now) : null;
  }, [shown]);

  return (
    <div className="home-timeline card">
      <div className="home-timeline-head">
        <span className="home-timeline-eq" aria-hidden>♪</span>
        <div className="home-timeline-song">
          <span className="song-strip-song-title">{title || 'No song'}</span>
          <span className="song-strip-song-artist">{artist}</span>
        </div>
        <div className="home-timeline-toggles">
          <IconToggle icon="scene" on={filters.analysed} onToggle={() => toggle('analysed')} title="Analysed events" />
          <IconToggle icon="pulse" on={filters.drop} onToggle={() => toggle('drop')} title="Drop sequences" />
          <IconToggle icon="arrowUp" on={filters.lightShow} onToggle={() => toggle('lightShow')} title="Light Show" />
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

      {next && (
        <div className="home-timeline-next" title={eventLabel(next)}>
          Next: {eventLabel(next)} in {fmtCountdown(Math.max(0, next.ms - (getShowClockMs() ?? next.ms)))}
        </div>
      )}

      {showAudioShape && (
        <div className="home-timeline-shape">
          <canvas ref={canvasRef} className="home-timeline-shape-canvas" />
          <div ref={canvasPlayheadRef} className="home-timeline-shape-playhead" />
        </div>
      )}
    </div>
  );
}
