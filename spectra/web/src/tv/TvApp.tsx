/** THE TV APP SHELL (data/tv-display-plan/plan.html PR 1.1, extended by
 * PR 1.5) — three planes stacked in one page, no app chrome, no bars:
 * the Visual plane (canvas, behind everything), the Info plane (DOM, the
 * content a person across the room actually reads), and the System
 * plane (a small diagnostic corner). `ConnectionOverlay` sits above all
 * three so the lost-connection screen (5s mark / 60s black) can cover
 * them without either plane needing to know about connection state
 * itself.
 *
 * SLEEP IS A SEPARATE, SMALLER TREE on purpose (PR 1.5): true black has
 * zero burn-in risk BECAUSE nothing is drawn — if the Visual plane's
 * haze or the System plane's status dot kept rendering underneath, a
 * sleep that holds for hours would itself become the static-pixel risk
 * this whole screen exists to avoid. */
import ConnectionOverlay from './ConnectionOverlay';
import InfoPlane from './InfoPlane';
import SleepScreen from './SleepScreen';
import SystemPlane from './SystemPlane';
import { useFeed } from './useFeed';
import VisualPlane from './VisualPlane';

export default function TvApp() {
  const feed = useFeed();
  if (feed.layout === 'sleep') {
    return (
      <main className="tv-app">
        <SleepScreen />
        <ConnectionOverlay />
      </main>
    );
  }
  return (
    <main className="tv-app">
      <VisualPlane />
      <InfoPlane />
      <SystemPlane />
      <ConnectionOverlay />
    </main>
  );
}
