/** THE INFO PLANE (DOM) — plan §7's architecture table: "now playing ·
 * votes · up next · board · QR". While connected and jukebox data has
 * landed: "party" renders the real Party screen (PR 1.4) and anything
 * else renders the real Attract screen (PR 1.5) — the TV app's own
 * two-screen content split. "Sleep" never reaches this component at all
 * (TvApp.tsx short-circuits to SleepScreen before InfoPlane mounts). Not
 * yet connected keeps the plain placeholder. */
import AttractScreen from './AttractScreen';
import PartyScreen from './PartyScreen';
import { useFeed } from './useFeed';

export default function InfoPlane() {
  const feed = useFeed();
  if (!feed.connected) {
    return (
      <div className="tv-info-plane" role="status" aria-live="polite">
        <div className="tv-info-title">SPECTRA TV</div>
        <div className="tv-info-sub">Connecting to SPECTRA…</div>
      </div>
    );
  }
  if (feed.layout === 'party' && feed.jukebox) {
    return <PartyScreen />;
  }
  return <AttractScreen />;
}
