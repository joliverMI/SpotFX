/** Home (`/`) — song-layout-plan, data/ui-layout-plan/report.md §5, §13
 * decision 10 ("/" opens Home instead of Scenes). An editable copy of the
 * global song timeline (icon toggles, draggable window, a tuned audio
 * shape sharing its playhead) full width on desktop, plus Quick
 * sequences / Quick actions cards side by side (never full width).
 *
 * The global, read-only SongStrip is hidden here (§13 decision 5 — Home
 * carries its own editable copy) by App.tsx's own route check, not by
 * anything in this file. */
import { useUpcoming, useEngineStatus } from '../queries';
import HomeTimeline from './HomeTimeline';
import HomeQuickRuns from './HomeQuickRuns';

export default function HomePage() {
  const { data: status } = useEngineStatus();
  const track = status?.bridge.track ?? null;
  const uri = track?.uri ?? null;
  const { data: upcoming } = useUpcoming(uri);

  return (
    <div className="home-page">
      {track ? (
        <HomeTimeline
          uri={uri}
          title={track.title ?? ''}
          artist={track.artist ?? ''}
          durationMs={track.duration_ms ?? 0}
          events={upcoming?.events ?? []}
        />
      ) : (
        <div className="card home-no-track">Nothing playing.</div>
      )}
      <HomeQuickRuns />
    </div>
  );
}
