/** THE INFO PLANE (DOM) — plan §7's architecture table: "now playing ·
 * votes · up next · board · QR". While the director's `layout` is
 * "party" and a jukebox payload has actually landed, this renders the
 * real Party screen (PR 1.4, PartyScreen.tsx). Anything else (not yet
 * connected, or "attract"/"sleep"/etc.) keeps the placeholder text — the
 * real Attract/Sleep/lost-connection screens are PR 1.5's own row. */
import PartyScreen from './PartyScreen';
import { useFeed } from './useFeed';

export default function InfoPlane() {
  const feed = useFeed();
  if (feed.connected && feed.layout === 'party' && feed.jukebox) {
    return <PartyScreen />;
  }
  const sub = !feed.connected
    ? 'Connecting to SPECTRA…'
    : 'Nothing playing — the Attract screen lands in a later PR.';
  return (
    <div className="tv-info-plane" role="status" aria-live="polite">
      <div className="tv-info-title">SPECTRA TV</div>
      <div className="tv-info-sub">{sub}</div>
    </div>
  );
}
