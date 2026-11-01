/** THE INFO PLANE (DOM) — plan §7's architecture table: "now playing ·
 * votes · up next · board · QR". Phase 1.1 ships the shell only; the feed
 * (1.2) and the Party/Attract/Sleep screens (1.4/1.5) fill this plane with
 * real content. Text sizes here already respect the room's reading-
 * distance floors (plan §2.4: body >= 32px, a now-playing title 64-80px at
 * ~3.5m from an 83" set) so later content slots into type that is already
 * the right size, rather than being re-sized once real text lands. */
export default function InfoPlane() {
  return (
    <div className="tv-info-plane" role="status" aria-live="polite">
      <div className="tv-info-title">SPECTRA TV</div>
      <div className="tv-info-sub">Building toward the Jukebox Party screen.</div>
    </div>
  );
}
