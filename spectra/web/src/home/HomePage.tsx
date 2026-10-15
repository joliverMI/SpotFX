/** Home (`/`) — song-layout-plan, data/ui-layout-plan/report.md §5, §13
 * decision 10 ("/" opens Home instead of Scenes): the tuned audio shape
 * aligned under the chrome's own song timeline, full width on desktop,
 * plus Quick sequences / Quick actions cards side by side (never full
 * width).
 *
 * THE TIMELINE IS NOT HERE ANY MORE (the Admiral, 2026-10-15). Home used
 * to draw its own editable copy of it directly above the shape, which is
 * the row that jumped down the page whenever he opened Home; the chrome's
 * single `components/SongStrip` row is now the timeline on every route,
 * and this page drives its window through the shared view state
 * (components/songTimelineView.tsx) rather than drawing a second one. */
import { useSongTimelineView } from '../components/songTimelineView';
import HomeTimeline from './HomeTimeline';
import HomeQuickRuns from './HomeQuickRuns';

export default function HomePage({ showAudioShape = true }: { showAudioShape?: boolean }) {
  // THE LAST SONG COUNTS (the Admiral's Q2 answer, 2026-10-15): with
  // nothing playing, Home shows the LAST song's shape DIMMED rather than
  // a bare "Nothing playing" card. The shared view state holds that
  // memory, so this shape and the timeline row above it are always
  // showing the same song. The card below is now reachable only on a
  // session where nothing has played at all.
  const { track, showingLast } = useSongTimelineView();
  const uri = track?.uri ?? null;

  return (
    <div className="home-page">
      {track ? (
        <HomeTimeline uri={uri} showAudioShape={showAudioShape} dimmed={showingLast} />
      ) : (
        <div className="card home-no-track">
          Nothing has played yet this session — the timeline above is waiting for a song.
        </div>
      )}
      <HomeQuickRuns />
    </div>
  );
}
