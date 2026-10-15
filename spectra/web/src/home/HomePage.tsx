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
import { useEngineStatus } from '../queries';
import HomeTimeline from './HomeTimeline';
import HomeQuickRuns from './HomeQuickRuns';

export default function HomePage({ showAudioShape = true }: { showAudioShape?: boolean }) {
  const { data: status } = useEngineStatus();
  const track = status?.bridge.track ?? null;
  const uri = track?.uri ?? null;

  return (
    <div className="home-page">
      {track ? (
        <HomeTimeline uri={uri} showAudioShape={showAudioShape} />
      ) : (
        // The timeline row above already says "Nothing playing" and draws
        // its own empty panel (it never unmounts — SongStrip.tsx's own
        // rule), so this is only about the SHAPE having nothing to draw.
        <div className="card home-no-track">Nothing playing.</div>
      )}
      <HomeQuickRuns />
    </div>
  );
}
