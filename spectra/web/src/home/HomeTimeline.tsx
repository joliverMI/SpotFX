/** HOME'S AUDIO SHAPE — the tuned canvas, ALIGNED under the global song
 * timeline, with the one thin control row beneath it.
 *
 * WHAT CHANGED, AND WHY (the Admiral, 2026-10-15, verbatim: "the home
 * page moves the timeline from the top bar down to right above the audio
 * graph. Here's what I would prefer: move the timeline below the toolbar
 * ... Then, on the home page, just make sure the audio shape graph is
 * aligned with the timeline"). This card used to draw its OWN copy of the
 * song timeline — a head with the title/artist/clock and its own strip —
 * which is exactly the row that jumped down the page on Home. Both are
 * GONE: the chrome's single `components/SongStrip` row is the timeline on
 * every route now, it carries the draggable window while this shape is
 * mounted, and this card is the shape plus its controls.
 *
 * THE SHAPE IS THE TIMELINE PAGE'S OWN RENDERER (design-fidelity pass,
 * 2026-10-14 — audit H5): the REAL `TimelineCanvas` + `BUILDER_LAYERS`
 * (filled RMS terrain, time axis, beat strips, analysed/drop/Light-Show
 * markers, the one playhead). Read-only: `triggers`/`events` are empty
 * and no editing pointer is wired, so nothing here can author anything —
 * the Timeline page stays the editor.
 *
 * ALIGNMENT IS MEASURED, NOT GUESSED (`alignToTrack` below). The timeline
 * row lives in the chrome, outside `<main>`, with its own song block and
 * next-event box either side of the track; this card lives inside
 * `<main>` with the page's own padding. So the shape's left/right are
 * written imperatively from the track's own measured box every time
 * either one resizes — never a hand-copied padding sum, which would be
 * wrong at the first breakpoint that moves the song block's width (the
 * row has three of them).
 *
 * ONE SONG-TIME AXIS: markers draw against raw song time (the convention
 * `songPositionMarkers` already uses, per debug/plannedEvents.ts), the
 * canvas's own `view.offsetMs` shifts the WAV-time shape onto it, and
 * `librosaOffsetMs` is deliberately ZERO here — see the `view` memo.
 * Both playheads read the ONE show clock (lib/showClock.ts).
 *
 * RESPONSIVENESS (the Admiral, 2026-10-14: "the audio shape isn't as
 * responsive"). `TimelineCanvas` is itself rAF-driven and DPR-aware with
 * its own "resize only when the measured size actually changed" guard, so
 * pointing the shape at it keeps PR 424's measured fix by construction.
 * The alignment writer is a ResizeObserver, not a render, and skips a
 * write that would not move anything — so it costs nothing per frame
 * either. */
import { useEffect, useMemo, useRef, useState } from 'react';
import Icon from '../components/Icon';
import IconToggle from '../components/IconToggle';
import InfoTip from '../components/InfoTip';
import { useSongTimelineShape, useSongTimelineView } from '../components/songTimelineView';
import TimelineCanvas from '../timeline/canvas/TimelineCanvas';
import { BUILDER_LAYERS } from '../timeline/canvas/layers';
import { computeAverages, computeMfccDistances } from '../timeline/canvas/data';
import type { LayerDataBag, ViewState } from '../timeline/canvas/frame';
import { buildDisplay } from '../timeline/dropSequences';
import { lightShowCueMarkers } from '../timeline/lightShowMarkers';
import { songPositionMarkers } from '../debug/plannedEvents';
import {
  useAnalysedPlan, useAudioShapeData, useAudioShapeMeta, useDropSequences,
  useLibrosa, useShowArms,
} from '../timeline/queries';
import { getShowClockMs } from '../lib/showClock';
import { AnalysedGlyph, DropSeqGlyph, LightShowGlyph } from './markerGlyphs';

/** THE MOCKUP'S OWN CANVAS HEIGHT, flat (`.sp .canvasbox canvas {
 * height: 230px }`) — the whole canvas, not a waveform area the lanes
 * then grow past. Home draws no per-beat score strips and no drop-
 * sequence snap rails (see `beatStrips: false` and the `rails: null`
 * below), so nothing is reserved under the waveform and this IS the
 * rendered height. */
const CANVAS_H = 230;

/** THE ALIGNMENT RULE, pure so the check can drive it with no DOM.
 *
 * IT IS A CORRECTION, NOT AN ABSOLUTE POSITION, and that is the whole
 * point: it reads where the canvas CURRENTLY is against where the track
 * is, and nudges the aligned block's own margin/width by exactly that
 * difference. The first version computed an absolute `track.left -
 * parent.left`, which is wrong by every bit of box model between the
 * two — the card's own padding and border, the shape frame's border —
 * and measured 18 px out at every width. A correction is immune to all
 * of it by construction, and self-heals if any of it ever changes.
 *
 * The margin/width relationship is 1:1, so one pass converges; `moved`
 * says whether a write is even needed, which is what keeps this from
 * re-triggering its own ResizeObserver forever. */
export const ALIGN_EPSILON_PX = 0.5;

export function alignCorrection(
  track: { left: number; width: number },
  canvas: { left: number; width: number },
  current: { marginLeft: number; width: number },
): { marginLeft: number; width: number; moved: boolean } {
  const dLeft = track.left - canvas.left;
  const dWidth = track.width - canvas.width;
  return {
    marginLeft: current.marginLeft + dLeft,
    width: current.width + dWidth,
    moved: Math.abs(dLeft) > ALIGN_EPSILON_PX || Math.abs(dWidth) > ALIGN_EPSILON_PX,
  };
}

export default function HomeTimeline({
  uri, showAudioShape = true, dimmed = false,
}: {
  uri: string | null;
  /** Nothing is playing and this is the LAST song's shape (his Q2
   * answer) — drawn dimmed, with the row above it carrying the "last
   * played" cue. Still fully interactive: the window, the filters and
   * the lanes all work on a remembered song. */
  dimmed?: boolean;
  /** The kiosk view's own small-screen rule (kiosk/kioskConfig.ts): drop
   * the audio shape rather than squeeze it illegible. With it off this
   * card renders nothing at all, and the timeline row above stays
   * read-only (nothing is listening to its window). */
  showAudioShape?: boolean;
}) {
  const { data: meta } = useAudioShapeMeta(showAudioShape ? uri : null);
  const { data: shape } = useAudioShapeData(showAudioShape ? uri : null, true);
  const { data: librosa } = useLibrosa(uri);
  const { data: analysedPlan } = useAnalysedPlan(uri);
  const { data: showArms } = useShowArms(!!uri);
  const { data: dropResp } = useDropSequences(uri);
  const offsetMs = Number(meta?.timestamp_offset_ms ?? 0);

  // THE SHARED VIEW STATE the chrome's timeline row owns (the window, the
  // marker filters, the view history) — this card's control row is where
  // he sets it, and registering as its listener is what turns the row's
  // own window overlay on.
  const { win, filters, toggleFilter, pushHistory, undo, redo, canUndo, canRedo } =
    useSongTimelineView();
  useSongTimelineShape(showAudioShape);

  // The mockup's own thin control row under the shape: which bands draw,
  // the marks, and the librosa lanes — real filters, wired straight into
  // the canvas's own ViewState (the same fields BuilderPage sets).
  const [bands, setBands] = useState({ total: true, bass: true, mid: true, high: true, marks: true });
  const [lanes, setLanes] = useState({ sections: true, beats: true, more: false });
  const [intensityBg, setIntensityBg] = useState(false);

  // ── the shape ──────────────────────────────────────────────────────────
  const averages = useMemo(() => (shape ? computeAverages(shape, 4000) : null), [shape]);
  const mfccDistances = useMemo(() => computeMfccDistances(librosa ?? null), [librosa]);
  const maxRms = useMemo(() => (shape ? Math.max(...shape.rms_total, 1e-9) : null), [shape]);
  const analysedMarkers = useMemo(
    () => (filters.analysed ? songPositionMarkers(analysedPlan) : []), [filters.analysed, analysedPlan]);
  const lightShowCues = useMemo(
    () => (filters.lightShow ? lightShowCueMarkers(analysedPlan?.show_cues, showArms, uri) : []),
    [filters.lightShow, analysedPlan, showArms, uri]);
  const dropSeqs = useMemo(
    () => (filters.drop ? buildDisplay(dropResp, { showDismissed: false, analysedApplies: analysedPlan?.applies ?? true }) : []),
    [filters.drop, dropResp, analysedPlan]);

  const view: ViewState = useMemo(() => ({
    filters: bands,
    avgFilters: { total: false, bass: false, mid: false, high: false },
    // Every MusicMark kind, gated as one by the "Marks" toggle below —
    // Home is a glance view, not the Timeline page's per-kind legend.
    markFilters: {
      bass_drop: bands.marks, bass_start: bands.marks, bass_end: bands.marks,
      power_up: bands.marks, power_down: bands.marks, quiet: bands.marks,
      charging: bands.marks, tempo_change: bands.marks,
    },
    librosaFilters: {
      sections: lanes.sections, beats: lanes.beats,
      // The mockup's own "⋯ More lanes: onsets, harmonic, bass, snare,
      // mfcc" — one toggle over the set, since Home is a glance view and
      // the Timeline page already has the per-lane legend.
      onsets: lanes.more, harmonic: lanes.more,
      bass: lanes.more, snare: lanes.more, mfcc: lanes.more,
    },
    scales: { total: 1, bass: 1, mid: 1, high: 1 },
    scaleOverall: 1,
    offsetMs,
    // ZERO, DELIBERATELY — the raw convention. `librosa_offset_ms` is
    // recorded in AGENTS.md as unreliable (nonzero on ~74% of his
    // analyses, with outliers into the tens of thousands of seconds, and
    // a per-song best-fit shift matched the stored number in 0 of 126
    // files), and the rule there is to read section/beat times RAW for
    // anything that has to line up with playback position. Reading them
    // raw here is also what makes this canvas internally consistent — the
    // section lanes, the beat ticks and the per-section intensity blocks
    // all on one axis — AND consistent with the timeline row's own energy
    // terrain above it, which is the agreement his "the intensity graph
    // should be by section, like the top bar timeline" asks for. The
    // Timeline page keeps its own convention (it is the editor and has
    // its own offset controls); this is Home's.
    librosaOffsetMs: 0,
    triggerOffsetMs: 0,
    maxRms,
    // BY SECTION, not the continuous RMS curve (his own 2026-10-15 ask):
    // one level per librosa section, drawn as blocks from the SAME
    // `sections[].energy_rms` the timeline row's terrain is built from
    // (components/songStrip.ts::terrainPath).
    intensityMode: intensityBg ? 'section' : 'off',
    advanced: false,
  }), [bands, lanes, intensityBg, offsetMs, maxRms]);

  const data: LayerDataBag = useMemo(() => ({
    shape: shape ?? null,
    averages,
    meta: meta ?? null,
    librosa: librosa ?? null,
    mfccDistances,
    triggers: [],
    events: [],
    calibrationTargetsMs: [],
    draggingIntensity: null,
    selectedIds: [],
    hoverTriggerId: null,
    plannedEvents: analysedMarkers,
    // No per-beat score strips (empty lanes here — see CANVAS_H) and no
    // `rails`: the snap rails are a drop-EDITING affordance, and Home is
    // a read-only glance view. Both would otherwise reserve height the
    // mockup's own canvas does not have.
    beatStrips: false,
    dropSeq: dropSeqs.length
      ? {
        seqs: dropSeqs, rails: null,
        selectedKey: null, hover: null, selectedHandle: null, adding: false, live: null,
        capturedFromMs: dropResp?.song?.captured_from_ms ?? null,
        beatMs: dropResp?.song?.beat_ms ?? 500,
      }
      : null,
    lightShow: lightShowCues,
  }), [shape, averages, meta, librosa, mfccDistances, analysedMarkers, dropSeqs,
       dropResp, lightShowCues]);

  // ── ALIGNED WITH THE TIMELINE TRACK ────────────────────────────────────
  const alignedRef = useRef<HTMLDivElement>(null);
  const canvasBoxRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!showAudioShape) return undefined;
    const apply = () => {
      const aligned = alignedRef.current;
      const canvasBox = canvasBoxRef.current;
      const track = document.querySelector('.song-strip-track');
      if (!aligned || !canvasBox || !track) return;
      const tr = track.getBoundingClientRect();
      const cr = canvasBox.getBoundingClientRect();
      const ar = aligned.getBoundingClientRect();
      // Neither side laid out yet (a hidden or zero-width track, a shape
      // the canvas has not sized) must ever be taken as a target.
      if (tr.width <= 1 || cr.width <= 1 || ar.width <= 1) return;
      const next = alignCorrection(
        { left: tr.left, width: tr.width },
        { left: cr.left, width: cr.width },
        {
          marginLeft: parseFloat(aligned.style.marginLeft) || 0,
          width: ar.width,
        },
      );
      if (!next.moved) return;
      aligned.style.marginLeft = `${next.marginLeft.toFixed(2)}px`;
      aligned.style.width = `${next.width.toFixed(2)}px`;
    };
    apply();
    const observer = new ResizeObserver(apply);
    const track = document.querySelector('.song-strip-track');
    if (track) observer.observe(track);
    if (alignedRef.current?.parentElement) observer.observe(alignedRef.current.parentElement);
    window.addEventListener('resize', apply);
    return () => { observer.disconnect(); window.removeEventListener('resize', apply); };
  }, [showAudioShape]);

  if (!showAudioShape) return null;

  return (
    <div className={`home-timeline card${dimmed ? ' home-timeline-dimmed' : ''}`}>
      {/* ONE element carries the measured alignment, so the shape and its
        * control row move together and there is one geometry writer. */}
      <div ref={alignedRef} className="home-timeline-aligned">
        <div ref={canvasBoxRef} className="home-timeline-shape">
          <TimelineCanvas
            layers={BUILDER_LAYERS}
            data={data}
            view={view}
            getWin={win.getWin}
            getNowMs={getShowClockMs}
            height={CANVAS_H}
          />
        </div>
        {/* ONE THIN ROW of controls, the mockup's own (audit H5). */}
        <div className="home-timeline-controls">
          <div className="home-timeline-controls-group">
            <IconToggle label="T" size={28} on={bands.total} title="Total RMS"
              onChange={() => setBands((b) => ({ ...b, total: !b.total }))} />
            <IconToggle label="B" size={28} on={bands.bass} title="Bass RMS"
              onChange={() => setBands((b) => ({ ...b, bass: !b.bass }))} />
            <IconToggle label="M" size={28} on={bands.mid} title="Mid RMS"
              onChange={() => setBands((b) => ({ ...b, mid: !b.mid }))} />
            <IconToggle label="H" size={28} on={bands.high} title="High RMS"
              onChange={() => setBands((b) => ({ ...b, high: !b.high }))} />
            <span className="home-timeline-vsep" aria-hidden />
            <IconToggle label="Marks" size={28} on={bands.marks} title="The song's own marks"
              onChange={() => setBands((b) => ({ ...b, marks: !b.marks }))} />
            <span className="home-timeline-vsep" aria-hidden />
            <IconToggle label="sections" size={28} on={lanes.sections} title="Librosa section boundaries"
              onChange={() => setLanes((l) => ({ ...l, sections: !l.sections }))} />
            <IconToggle label="beats" size={28} on={lanes.beats} title="Librosa beat strips"
              onChange={() => setLanes((l) => ({ ...l, beats: !l.beats }))} />
            <IconToggle icon="more" size={28} on={lanes.more}
              title="More lanes: onsets, harmonic, bass, snare, mfcc"
              onChange={() => setLanes((l) => ({ ...l, more: !l.more }))} />
          </div>
          <div className="home-timeline-controls-group">
            {/* THE MARKER FILTERS, IMMEDIATELY LEFT OF THE INTENSITY BOLT
              * (his own 2026-10-15 placement). Same component, same look
              * as the ones that used to sit in this card's retired head —
              * and they govern BOTH this shape and the timeline row above
              * it, since both read the one shared filter set. */}
            <IconToggle glyph={AnalysedGlyph} size={28} on={filters.analysed}
              onChange={() => toggleFilter('analysed')}
              title="Analysed events (scene changes and flares)" />
            <IconToggle glyph={DropSeqGlyph} size={28} on={filters.drop}
              onChange={() => toggleFilter('drop')} title="Drop sequences" />
            <IconToggle glyph={LightShowGlyph} size={28} on={filters.lightShow}
              onChange={() => toggleFilter('lightShow')}
              title="Light Show High / Low triggers" />
            <IconToggle icon="bolt" size={28} on={intensityBg}
              title="Shade the background by the song's own section energy"
              onChange={() => setIntensityBg((v) => !v)} />
            <span className="home-timeline-vsep" aria-hidden />
            {/* THE VIEW CONTROLS for the window drawn on the timeline row
              * above (audit H2 kept them beside Follow / Full song; they
              * live here now, with the shape they actually govern). */}
            <button type="button" className="home-timeline-tool" onClick={undo} disabled={!canUndo}
              title="Undo the last view change" aria-label="Undo the last view change">
              <Icon name="undo" size={15} />
            </button>
            <button type="button" className="home-timeline-tool" onClick={redo} disabled={!canRedo}
              title="Redo the view change" aria-label="Redo the view change">
              <Icon name="redo" size={15} />
            </button>
            <button type="button" className={`home-timeline-tool${win.follow ? ' home-timeline-tool-on' : ''}`}
              title="Follow the playhead" aria-label="Follow the playhead"
              onClick={() => { pushHistory(); win.setFollowSnapped(!win.follow); }}>
              <Icon name="follow" size={15} />
            </button>
            <button type="button" className="home-timeline-tool" title="Whole song" aria-label="Whole song"
              onClick={() => { pushHistory(); win.fullSong(); }}>
              <Icon name="full" size={15} />
            </button>
            <InfoTip topic="builder-analysed-events"
              text="Cyan squares are scene changes and lime dots analysed flares, sized and shaded by rank. Gold is a charge, sky a lull, pink a drop. White and indigo flags are the Light Show's High and Low Triggers. Drag the window on the timeline above to choose what this shows.">
              <span className="home-timeline-tool home-timeline-tool-wide">
                <Icon name="info" size={14} /> Legend
              </span>
            </InfoTip>
            <a className="home-timeline-tool home-timeline-tool-wide" href="/spectra/timeline"
              title="Open the Timeline page to edit this song">
              <Icon name="timeline" size={14} /> Timeline
            </a>
          </div>
        </div>
      </div>
    </div>
  );
}
