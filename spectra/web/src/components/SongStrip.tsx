/** THE GLOBAL SONG TIMELINE (song-layout-plan, data/ui-layout-plan/
 * report.md §4): a 39 px track in a 53 px row, BELOW THE ONE BAR (the
 * Admiral, 2026-10-15 — see components/AppChrome.tsx), on every page
 * except the Timeline page, which carries its own full toolset.
 *
 * IT IS THE ONLY COPY NOW, AND HOME EDITS IT. Home used to draw a second,
 * editable timeline directly above its audio shape, so the row jumped
 * from the chrome down the page whenever he opened Home (his own report).
 * This row is now the one he sees everywhere; while Home's audio shape is
 * mounted it also carries a draggable WINDOW overlay that sets what that
 * shape shows. The window, the marker filters and the view history all
 * live in components/songTimelineView.tsx — the shared state AppChrome
 * provides — so neither element owns the other.
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
import { useEffect, useMemo, useRef } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import {
  fmtMMSS, MARKER_CY, PLAYED_TINT, pickNext, ringCy, TRACK_HEIGHT, TRACK_PAD, trackX,
} from './songStrip';
import SongNextBox, { useNextBoxInBar } from './SongNextBox';
import { paintTrack, type MarkNode } from './trackPainter';
import { useEnergyTimeline, useEngineStatus, useUpcoming } from '../queries';
import { getPositionMs, getShowClockMs } from '../lib/showClock';
import InfoTip from './InfoTip';
import { kindShown, useSongTimelineView } from './songTimelineView';

export default function SongStrip() {
  const { data: status } = useEngineStatus();
  // THE SHARED VIEW STATE (components/songTimelineView.tsx): which marker
  // kinds draw (set from Home's own control row), the draggable window
  // this row owns while Home's shape is listening, and THE RESOLVED
  // TRACK — the live one, or the last one seen this session (his Q2
  // answer, 2026-10-15): with nothing playing this row shows the LAST
  // song's timeline, dimmed and labelled, rather than an empty panel.
  // One resolved track for both surfaces, so Home's shape below is
  // always showing the same song this row is.
  const { filters, editable, win, pushHistory, track, showingLast, selectDrop } =
    useSongTimelineView();
  const uri = track?.uri ?? null;
  const navigate = useNavigate();
  const location = useLocation();
  const { data: upcoming } = useUpcoming(uri);
  // The terrain's own source: the song's ENERGY timeline (spectra/services/
  // energy.py — the number the engine acts on, Mark included, in song
  // time). Shares react-query's cache with the top bar, Home and the
  // Timeline page; a song with no analysis draws no terrain.
  const { data: energyTl } = useEnergyTimeline(uri);
  // WHERE THE NEXT-EVENT BOX LIVES at this width (his Q1 answer) — the
  // one predicate, shared with TopBarStrip, so it is never in both
  // places and never in neither.
  const nextInBar = useNextBoxInBar();
  const allEvents = upcoming?.events;
  const events = useMemo(
    () => (allEvents ?? []).filter((e) => kindShown(e.kind, filters)),
    [allEvents, filters]);
  const durationMs = track?.duration_ms ?? 0;
  const sections = energyTl?.status === 'ok' ? energyTl.sections : null;
  // Read through a ref so the rAF loop below never re-runs when an
  // unrelated render hands `useFollowWindow` a fresh object identity
  // (only its own `getWin` is memoized — that module's own contract).
  const winRef = useRef(win);
  winRef.current = win;

  const trackRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const bodyGroupRef = useRef<SVGGElement>(null);
  const playedRef = useRef<SVGRectElement>(null);
  const ringGroupRef = useRef<SVGGElement>(null);
  const ringRef = useRef<SVGCircleElement>(null);
  const playheadRef = useRef<SVGGElement>(null);
  const timeRef = useRef<HTMLSpanElement>(null);
  const flashedKeyRef = useRef<string | null>(null);
  /** Every marker node by its own ms, so the rAF loop can fade a passed
   * marker (`.song-strip-mk-past`) and flash the one that just fired
   * (audit T6: the mockup flashes the MARKER, not only the box). */
  const markNodesRef = useRef<MarkNode[]>([]);
  const windowOverlayRef = useRef<HTMLDivElement>(null);

  // Rebuild the drawn body when WHAT is drawn changes (song, plan,
  // sections) — the per-frame loop below only ever moves the playhead /
  // played tint / ring / next-event text. ALSO rebuilt on resize (a
  // ResizeObserver, not a dep): paintTrack rewrites the SVG's viewBox to
  // match its own rendered width/height (songStrip.ts's `trackX`
  // docstring), which changes independently of the song.
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

      // THE WINDOW OVERLAY (Home only — `editable`). Positioned with the
      // track's OWN `trackX` mapping, in px, not a raw percentage of the
      // row: the markers are drawn inside the panel's TRACK_PAD inset, so
      // a percentage overlay sat up to a pad's width off the markers it
      // is meant to bracket. Moved here, in the one rAF loop, rather than
      // in React — a drag must never cost a render per pointermove.
      if (windowOverlayRef.current) {
        if (!editable || durationMs <= 0 || svgW <= 0) {
          windowOverlayRef.current.style.display = 'none';
        } else {
          const w = winRef.current.getWin();
          const left = atX(w.startMs);
          const right = atX(w.endMs);
          windowOverlayRef.current.style.display = 'block';
          windowOverlayRef.current.style.left = `${left.toFixed(2)}px`;
          windowOverlayRef.current.style.width = `${Math.max(2, right - left).toFixed(2)}px`;
        }
      }

      // THE "IT IS NEXT" RING AND THE MARKER FLASH stay here — both are
      // drawn ON the track. The next-event BOX's own countdown/glyph/fill
      // live in components/SongNextBox.tsx, which owns its own rAF loop
      // because at <=1100px it is mounted in the BAR instead of here
      // (his Q1 answer). Both pick the same event by the same `pickNext`,
      // so they can never disagree about what is next.
      const next = now != null ? pickNext(events, now) : null;
      if (next) {
        const key = `${next.ms}:${next.kind}`;
        if (ringGroupRef.current && ringRef.current && durationMs > 0 && svgW > 0) {
          const h = svgRect?.height ?? TRACK_HEIGHT;
          ringGroupRef.current.setAttribute('opacity', '1');
          ringRef.current.setAttribute('cx', atX(next.ms).toFixed(2));
          ringRef.current.setAttribute('cy', String(ringCy(next.kind) * (h / TRACK_HEIGHT)));
        }
        if (next.ms - (now as number) <= 0 && flashedKeyRef.current !== key) {
          flashedKeyRef.current = key;
          // THE MARKER FLASHES (audit T6 / approved idea 3) — the live
          // strip only ever flashed the box.
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
  }, [events, durationMs, editable]);

  /** A TAP ON A DROP PILL (predrop plan step 1's tie-in): the drop it
   * names is selected in Home's Drops panel and scrolled into view — and
   * from any other page, Home opens on it. True when a drop was hit. */
  const tapDrop = (clientX: number): boolean => {
    const svg = svgRef.current;
    if (!svg || durationMs <= 0) return false;
    const r = svg.getBoundingClientRect();
    const x = clientX - r.left;
    let best: number | null = null;
    let bestD = 12;                        // px: a finger on a 12 px pill
    for (const e of events) {
      if (e.kind !== 'drop') continue;
      const d = Math.abs(trackX(e.ms, durationMs, r.width) - x);
      if (d <= bestD) { best = e.ms; bestD = d; }
    }
    if (best == null) return false;
    selectDrop(uri, best);
    if (location.pathname !== '/') navigate('/');
    return true;
  };

  /** THE WINDOW DRAG — TimelineBar's own `dragEdge` shape (BuilderPage's
   * `onAdjustFollow` convention), moved here from Home's retired copy of
   * the strip: in follow mode an EDGE drag resizes the look-behind /
   * look-ahead, and a CENTRE drag always detaches into a manual pan (the
   * plan's own "dragging leaves Follow" rule). One history step per
   * committed drag, pushed on pointerdown. */
  const dragWin = (edge: 'start' | 'end' | 'center') => (ev: React.PointerEvent) => {
    ev.preventDefault();
    ev.stopPropagation();
    const svg = svgRef.current;
    if (!svg || durationMs <= 0) return;
    const target = ev.target as HTMLElement;
    target.setPointerCapture(ev.pointerId);
    let lastX = ev.clientX;
    const startX = ev.clientX;
    // ONE history step per drag, pushed when it really moves — a tap on
    // the window (a drop pill under it) is not a drag and leaves no step
    let moved = false;
    const move = (e: PointerEvent) => {
      if (!moved) {
        if (Math.abs(e.clientX - startX) < 4) return;
        moved = true;
        pushHistory();
      }
      // The drag's own px→ms scale is the TRACK's, inset included, so a
      // pointer moving over a marker moves the window to that marker.
      const rect = svg.getBoundingClientRect();
      const span = Math.max(1, rect.width - 2 * TRACK_PAD);
      const deltaMs = ((e.clientX - lastX) / span) * Math.max(1, durationMs);
      lastX = e.clientX;
      if (win.follow && edge !== 'center') {
        if (edge === 'end') win.setFutureS((sec) => Math.max(0, sec + deltaMs / 1000));
        else win.setWindowS((sec) => Math.max(2, sec - deltaMs / 1000));
        return;
      }
      const w = win.getWin();
      if (edge === 'center') win.setManualWin({ startMs: w.startMs + deltaMs, endMs: w.endMs + deltaMs });
      else if (edge === 'start') {
        win.setManualWin({ startMs: Math.min(w.startMs + deltaMs, w.endMs - 1000), endMs: w.endMs });
      } else {
        win.setManualWin({ startMs: w.startMs, endMs: Math.max(w.endMs + deltaMs, w.startMs + 1000) });
      }
      if (edge === 'center' && win.follow) win.setFollow(false);
    };
    const up = (e: PointerEvent) => {
      try { target.releasePointerCapture(e.pointerId); } catch { /* already gone */ }
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
      window.removeEventListener('pointercancel', up);
      if (!moved && e.type === 'pointerup') tapDrop(e.clientX);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
    // A gesture the browser takes over fires this instead of pointerup —
    // without it a drag could stick with no pointerup to clear it.
    window.addEventListener('pointercancel', up);
  };

  // A REMEMBERED SONG IS NEVER "PLAYING" — its `is_playing` was true
  // when it was captured, and an animating equaliser on a room that has
  // gone quiet is exactly the claim the "last played" cue exists to deny.
  const playing = !showingLast && Boolean(track?.is_playing);
  const title = track?.title ?? null;
  // UP NEXT ON HOVER (approved idea 7) — already on the wire
  // (bridge.status()'s own `next_track`, Show Playlists' read half), so
  // this is a pure read: no new endpoint, no poll of its own.
  const upNext = status?.bridge.next_track?.title || null;

  return (
    <div className={`song-strip${nextInBar ? ' song-strip-no-next' : ''}`
        + `${showingLast ? ' song-strip-last' : ''}`}>
      {/* THE SONG BLOCK TAPS THROUGH TO HOME (audit T2) with an animated
        * three-bar equaliser while a song plays, title above artist, and
        * no circle of its own — the description lives on hover. */}
      <InfoTip
        className="song-strip-song-tip"
        topic="song-timeline"
        text={`${showingLast
          ? 'The LAST song played — nothing is playing right now, so this is dimmed. '
          : ''}The whole song with the same markers Home shows, and the next thing that will actually fire — its type and a countdown. Tap to open Home.${
          upNext ? ` Up next: ${upNext}.` : ''}`}
      >
        <Link to="/" className="song-strip-song"
            aria-label={title
              ? `${title}${showingLast ? ' (last played, nothing playing now)' : ''} — tap to open Home`
              : 'Nothing playing — tap to open Home'}>
          <span className={`song-strip-eq${playing ? '' : ' song-strip-eq-still'}`} aria-hidden>
            <i /><i /><i />
          </span>
          <span className="song-strip-song-text">
            <span className="song-strip-song-title">{title || 'Nothing playing'}</span>
            <span className="song-strip-song-artist">
              {/* A CLEAR "last played" CUE (his Q2 answer) — it must never
                * be possible to read a remembered song as a playing one. */}
              {showingLast ? 'last played' : (track?.artist || '')}
            </span>
          </span>
        </Link>
      </InfoTip>

      <div ref={trackRef} className="song-strip-track" style={{ height: TRACK_HEIGHT }}
          onClick={(e) => { tapDrop(e.clientX); }}>
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
        {/* ALWAYS MOUNTED, hidden by the rAF loop when nothing is
          * listening to the window — a conditionally-mounted overlay
          * would make `editable` flipping a React render in the middle of
          * a drag, and this element has a pointer capture on it. */}
        <div ref={windowOverlayRef} className="song-strip-window"
            style={{ display: 'none' }} onPointerDown={dragWin('center')}
            // the drag's own pointerup already handled a tap on a pill
            onClick={(e) => e.stopPropagation()}
            title="Drag to choose what the audio shape below shows">
          <div className="song-strip-window-edge left" onPointerDown={dragWin('start')} />
          <div className="song-strip-window-edge right" onPointerDown={dragWin('end')} />
        </div>
      </div>

      {/* AT <=1100px THIS BOX IS IN THE BAR INSTEAD (his Q1 answer) —
        * mounted by TopBarStrip, never both at once. */}
      {!nextInBar && <SongNextBox events={events} durationMs={durationMs} host="strip" />}

      <span className="song-strip-time tabular-nums">
        <b ref={timeRef}>—:—</b> / {durationMs > 0 ? fmtMMSS(durationMs) : '—:—'}
      </span>
    </div>
  );
}
