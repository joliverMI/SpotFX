/** THE GLOBAL SONG TIMELINE (song-layout-plan, data/ui-layout-plan/
 * report.md §4): a 39 px track in a 53 px row between the menu and the
 * top bar, on every page except Home (its own editable copy) and the
 * Timeline page (its own full toolset) — §13 decision 5.
 *
 * IT NEVER UNMOUNTS (design-fidelity pass, 2026-10-14 — audit T1/P2/N2,
 * the single biggest reason the live app did not look like the approved
 * artifact). `if (!track) return null;` removed the whole row whenever
 * nothing was playing, which is the state he reviewed the deploy in: the
 * artifact's signature element was off screen most of the day, and its
 * appearance was itself a 39 px layout jump on every page (plan §5's own
 * "nothing jumps" rule). The row is now always present; with no song it
 * draws the empty panel, "Nothing playing", and the mockup's own "—" in
 * the next-event box (its `f-nxstates` frame's right-most state).
 *
 * THE TRACK IS DRAWN AS THE MOCKUP DRAWS IT (audit T3): an inset rounded
 * panel, a faint energy terrain of the song's own section energies
 * (approved idea 4 — real librosa data, see songStrip.ts::terrainPath),
 * the played portion tinted purple, drop sequences as a gold charge bar →
 * a sky lull bar → a pink numbered drop pill, High/Low flags with
 * triangular heads from the top edge, rank-sized scene/flare markers, a
 * pulsing ring on whatever fires next, and a triangle-headed playhead.
 *
 * Markers are static SVG, rebuilt only when the song or its plan changes
 * (react-query already invalidates on its own cadence); the playhead, the
 * played tint, the ring, the next-event countdown and the one-shot fire
 * flash move in ONE rAF loop that writes attributes/textContent directly
 * — never a React render per frame (report §4.2). Both read the ONE show
 * clock (lib/showClock.ts) — the exact moment the trigger poll fires
 * against, not raw Spotify progress. */
import { useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import {
  countdownParts, eventLabel, FINAL_STRETCH_MS, fmtMMSS, kindGlyphSvg, MARKER_CY,
  NEXT_EVENT_BOX_WIDTH, PLAYED_TINT, pickNext, ringCy, TRACK_HEIGHT, trackX,
} from './songStrip';
import { paintTrack, type MarkNode } from './trackPainter';
import { useEngineStatus, useUpcoming } from '../queries';
import { useLibrosa } from '../timeline/queries';
import { getPositionMs, getShowClockMs } from '../lib/showClock';
import InfoTip from './InfoTip';

export default function SongStrip() {
  const { data: status } = useEngineStatus();
  const track = status?.bridge.track ?? null;
  const uri = track?.uri ?? null;
  const { data: upcoming } = useUpcoming(uri);
  // The terrain's own source: librosa's per-section energy (approved idea
  // 4). Shares react-query's cache with the Timeline/debug pages, so a
  // song already looked at costs nothing here; `retry: false` means a song
  // with no analysis simply draws no terrain.
  const { data: librosa } = useLibrosa(uri);
  const events = upcoming?.events ?? [];
  const durationMs = track?.duration_ms ?? 0;
  const sections = librosa?.sections ?? null;

  const trackRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const bodyGroupRef = useRef<SVGGElement>(null);
  const playedRef = useRef<SVGRectElement>(null);
  const ringGroupRef = useRef<SVGGElement>(null);
  const ringRef = useRef<SVGCircleElement>(null);
  const playheadRef = useRef<SVGGElement>(null);
  const timeRef = useRef<HTMLSpanElement>(null);
  const nextIconRef = useRef<SVGSVGElement>(null);
  const nextFillRef = useRef<HTMLDivElement>(null);
  const nextCountRef = useRef<HTMLSpanElement>(null);
  const nextUnitRef = useRef<HTMLElement>(null);
  const nextBoxRef = useRef<HTMLDivElement>(null);
  const flashedKeyRef = useRef<string | null>(null);
  const lastNextKindRef = useRef<string | null>(null);
  /** Every marker node by its own ms, so the rAF loop can fade a passed
   * marker (`.song-strip-mk-past`) and flash the one that just fired
   * (audit T6: the mockup flashes the MARKER, not only the box). */
  const markNodesRef = useRef<MarkNode[]>([]);

  // Rebuild the drawn body when WHAT is drawn changes (song, plan,
  // sections) — the per-frame loop below only ever moves the playhead /
  // played tint / ring / next-event text. ALSO rebuilt on resize (a
  // ResizeObserver, not a dep): the viewBox's own axis stretch (see
  // songStrip.ts's `axisScale` docstring) depends on the SVG's rendered
  // width/height, which change independently of the song.
  useEffect(() => {
    const svg = svgRef.current;
    const group = bodyGroupRef.current;
    if (!svg || !group) return undefined;

    const build = () => {
      markNodesRef.current = paintTrack(svg, group, { events, durationMs, sections });
    };

    build();
    const observer = new ResizeObserver(build);
    observer.observe(svg);
    return () => observer.disconnect();
  }, [events, durationMs, sections]);

  // THE ONE rAF LOOP — played tint, playhead, the "next" ring, the
  // countdown/fill, passed-marker fade, and the one-shot fire flashes.
  // No React state anywhere in here.
  useEffect(() => {
    let raf = 0;
    const tick = () => {
      const now = getShowClockMs();
      const pos = getPositionMs();
      const svgRect = svgRef.current?.getBoundingClientRect();
      const svgW = svgRect?.width ?? 0;
      const atX = (ms: number) => trackX(ms, durationMs, svgW);

      if (now != null && durationMs > 0 && svgW > 0) {
        const px = atX(now);
        playheadRef.current?.setAttribute('transform', `translate(${px.toFixed(2)},0)`);
        playheadRef.current?.setAttribute('opacity', '1');
        playedRef.current?.setAttribute('width', String(Math.max(0, px - 1).toFixed(2)));
      } else {
        playheadRef.current?.setAttribute('opacity', '0');
        playedRef.current?.setAttribute('width', '0');
      }

      if (timeRef.current) {
        timeRef.current.textContent = pos != null && durationMs > 0 ? fmtMMSS(pos) : '—:—';
      }

      const next = now != null ? pickNext(events, now) : null;
      if (next) {
        const remaining = next.ms - (now as number);
        const key = `${next.ms}:${next.kind}`;
        const glyphKey = `${next.kind}:${next.num ?? ''}`;
        if (nextIconRef.current && lastNextKindRef.current !== glyphKey) {
          lastNextKindRef.current = glyphKey;
          nextIconRef.current.innerHTML = kindGlyphSvg(next.kind, next.num);
        }
        const parts = countdownParts(remaining);
        if (nextCountRef.current) nextCountRef.current.textContent = parts.value;
        if (nextUnitRef.current) nextUnitRef.current.textContent = parts.unit ?? '';
        if (nextBoxRef.current) nextBoxRef.current.title = eventLabel(next);
        if (ringGroupRef.current && ringRef.current && durationMs > 0 && svgW > 0) {
          const h = svgRect?.height ?? TRACK_HEIGHT;
          ringGroupRef.current.setAttribute('opacity', '1');
          ringRef.current.setAttribute('cx', atX(next.ms).toFixed(2));
          ringRef.current.setAttribute('cy', String(ringCy(next.kind) * (h / TRACK_HEIGHT)));
        }
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
          // THE MARKER FLASHES TOO (audit T6 / approved idea 3) — the
          // live strip only ever flashed the box.
          for (const m of markNodesRef.current) {
            if (Math.abs(m.ms - next.ms) > 1) continue;
            m.node.classList.remove('song-strip-mk-flash');
            void (m.node as unknown as { getBoundingClientRect: () => DOMRect }).getBoundingClientRect();
            m.node.classList.add('song-strip-mk-flash');
            const node = m.node;
            setTimeout(() => node.classList.remove('song-strip-mk-flash'), 600);
          }
        }
      } else {
        if (nextCountRef.current) nextCountRef.current.textContent = '—';
        if (nextUnitRef.current) nextUnitRef.current.textContent = '';
        if (nextIconRef.current) { nextIconRef.current.innerHTML = ''; lastNextKindRef.current = null; }
        if (nextBoxRef.current) nextBoxRef.current.title = durationMs > 0 ? 'Nothing left this song' : 'Nothing playing';
        if (nextFillRef.current) nextFillRef.current.style.transform = 'scaleX(0)';
        nextBoxRef.current?.classList.remove('song-strip-next-soon');
        ringGroupRef.current?.setAttribute('opacity', '0');
      }

      // Passed markers fade (the mockup's own `.mk.past`).
      if (now != null) {
        for (const m of markNodesRef.current) {
          m.node.classList.toggle('song-strip-mk-past', m.ms < now - 50);
        }
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [events, durationMs]);

  const playing = Boolean(track?.is_playing);
  const title = track?.title ?? null;
  // UP NEXT ON HOVER (approved idea 7) — already on the wire
  // (bridge.status()'s own `next_track`, Show Playlists' read half), so
  // this is a pure read: no new endpoint, no poll of its own.
  const upNext = status?.bridge.next_track?.title || null;

  return (
    <div className="song-strip">
      {/* THE SONG BLOCK TAPS THROUGH TO HOME (audit T2) with an animated
        * three-bar equaliser while a song plays, title above artist, and
        * no circle of its own — the description lives on hover. */}
      <InfoTip
        className="song-strip-song-tip"
        topic="song-timeline"
        text={`The whole song with the same markers Home shows, and the next thing that will actually fire — its type and a countdown. Tap to open Home.${
          upNext ? ` Up next: ${upNext}.` : ''}`}
      >
        <Link to="/" className="song-strip-song" aria-label={title ? `${title} — tap to open Home` : 'Nothing playing — tap to open Home'}>
          <span className={`song-strip-eq${playing ? '' : ' song-strip-eq-still'}`} aria-hidden>
            <i /><i /><i />
          </span>
          <span className="song-strip-song-text">
            <span className="song-strip-song-title">{title || 'Nothing playing'}</span>
            <span className="song-strip-song-artist">{track?.artist || ''}</span>
          </span>
        </Link>
      </InfoTip>

      <div ref={trackRef} className="song-strip-track" style={{ height: TRACK_HEIGHT }}>
        {/* The viewBox is REWRITTEN to the measured pixel size on every
          * build (and on resize) — see songStrip.ts's `trackX` docstring.
          * `preserveAspectRatio="none"` is kept so a sub-pixel rounding
          * difference between the attribute and the box never letterboxes
          * the panel. */}
        <svg ref={svgRef} className="song-strip-svg" preserveAspectRatio="none"
            viewBox={`0 0 100 ${TRACK_HEIGHT}`} role="img"
            aria-label={title ? `${title}: whole song with planned events` : 'No song'}>
          <g ref={bodyGroupRef} />
          <rect ref={playedRef} className="song-strip-played" x="0" y="1" width="0"
              height={TRACK_HEIGHT - 2} fill={PLAYED_TINT} />
          <g ref={ringGroupRef} opacity="0">
            <circle ref={ringRef} className="song-strip-ring" cx="0" cy={MARKER_CY} r="9"
                fill="none" stroke="var(--accent2)" strokeWidth="1.6" />
          </g>
          <g ref={playheadRef} opacity="0">
            <line x1="0" x2="0" y1="0" y2={TRACK_HEIGHT} className="song-strip-playhead" />
            <path d="M-4 0 L4 0 L0 5Z" fill="#fff" />
          </g>
        </svg>
      </div>

      <div ref={nextBoxRef} className="song-strip-next" style={{ width: NEXT_EVENT_BOX_WIDTH }}>
        <div ref={nextFillRef} className="song-strip-next-fill" />
        {/* The TYPE GLYPH IS THE MARKER SHAPE, filled and kind-coloured
          * (songStrip.ts::kindGlyphSvg) — swapped with one innerHTML write
          * from the rAF loop, never a React render. */}
        <svg ref={nextIconRef} viewBox="0 0 16 16" width={18} height={18}
            className="song-strip-next-icon" aria-hidden="true" />
        <span className="song-strip-next-count tabular-nums">
          <span ref={nextCountRef}>—</span>
          <small ref={nextUnitRef} />
        </span>
      </div>

      <span className="song-strip-time tabular-nums">
        <b ref={timeRef}>—:—</b> / {durationMs > 0 ? fmtMMSS(durationMs) : '—:—'}
      </span>
    </div>
  );
}
