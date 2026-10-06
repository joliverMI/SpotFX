/** Generated (analysed) scene changes and flares on the full-song strip,
 * under his SPECTRA triggers strip and the drop-sequence strip — his ask,
 * verbatim: "I want to see the generated flares on the timeline. I see
 * them on the audio shape." They already drew on the audio-shape canvas
 * (../../debug/plannedEvents.ts's `songPositionMarkers`, drawn by
 * ../canvas/layers.ts's `analysedEvents` layer); this is the SAME marker
 * list (one source, one placement — never a second idea of what will
 * fire, so it already excludes anything a drop sequence's protected
 * window holds back — see spectra/api/analysed_plan.py's own docstring),
 * drawn as a thin row of ticks so they read against his triggers without
 * scrolling to the big graph. Read-only. */
import {
  FLARE_DOT_RADIUS, FLARE_MARKER_COLOR, SCENE_MARKER_COLOR, SCENE_TAB_HALF_WIDTH,
  markerTooltip, rankOpacity, rankTier,
} from '../../debug/plannedEvents';
import type { PlannedEventMarker } from '../canvas/frame';

export default function AnalysedEventsStrip({ markers, durationMs }: {
  markers: PlannedEventMarker[];
  durationMs: number;
}) {
  const dur = Math.max(1, durationMs);
  const pct = (ms: number) => `${Math.max(0, Math.min(100, (ms / dur) * 100))}%`;

  return (
    <div className="analysed-events-strip" role="list" aria-label="Generated scene changes and analysed flares across the song">
      {markers.map((m, i) => {
        const tier = rankTier(m.rank, m.rankOf);
        const isScene = m.kind === 'scene';
        const color = isScene ? SCENE_MARKER_COLOR : FLARE_MARKER_COLOR;
        const opacity = rankOpacity(m.rank, m.rankOf, isScene ? 0.9 : 0.85);
        const size = isScene
          ? (tier == null ? 10 : SCENE_TAB_HALF_WIDTH[tier] * 2)
          : (tier == null ? 7 : FLARE_DOT_RADIUS[tier] * 2);
        return (
          <span
            key={`${m.kind}-${m.ms}-${i}`}
            role="listitem"
            title={markerTooltip(m)}
            style={{
              position: 'absolute', left: pct(m.ms), top: '50%',
              width: size, height: size, marginLeft: -size / 2, marginTop: -size / 2,
              borderRadius: isScene ? 2 : '50%', background: color, opacity,
            }}
          />
        );
      })}
      {!markers.length && (
        <span className="analysed-events-strip-empty">no generated scene changes or analysed flares planned</span>
      )}
    </div>
  );
}
