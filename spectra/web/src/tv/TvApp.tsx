/** THE TV APP SHELL (data/tv-display-plan/plan.html PR 1.1) — three
 * planes stacked in one page, no app chrome, no bars: the Visual plane
 * (canvas, behind everything), the Info plane (DOM, the content a person
 * across the room actually reads), and the System plane (a small
 * diagnostic corner). The feed (PR 1.2) and the real screens (Party /
 * Attract / Sleep / lost-connection, PRs 1.4-1.5) replace the Info plane's
 * placeholder content; this shell's structure doesn't change under them. */
import InfoPlane from './InfoPlane';
import SystemPlane from './SystemPlane';
import VisualPlane from './VisualPlane';

export default function TvApp() {
  return (
    <main className="tv-app">
      <VisualPlane />
      <InfoPlane />
      <SystemPlane />
    </main>
  );
}
