/** THE INFO PLANE (DOM) — plan §7's architecture table: "now playing ·
 * votes · up next · board · QR". The feed (PR 1.2) now tells this plane
 * whether it's connected and what the director picked; the real
 * Party/Attract/Sleep screens (PRs 1.4/1.5) replace this placeholder text
 * with that content. Text sizes here already respect the room's reading-
 * distance floors (plan §2.4: body >= 32px, a now-playing title 64-80px at
 * ~3.5m from an 83" set) so later content slots into type that is already
 * the right size, rather than being re-sized once real text lands. */
import { useFeed } from './useFeed';

export default function InfoPlane() {
  const feed = useFeed();
  const sub = !feed.connected
    ? 'Connecting to SPECTRA…'
    : feed.layout === 'party'
      ? 'A night is running — the Party screen lands in a later PR.'
      : 'Nothing playing — the Attract screen lands in a later PR.';
  return (
    <div className="tv-info-plane" role="status" aria-live="polite">
      <div className="tv-info-title">SPECTRA TV</div>
      <div className="tv-info-sub">{sub}</div>
    </div>
  );
}
