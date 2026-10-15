/** THE CHROME, IN ONE PLACE — the menu, the song timeline and the one
 * consolidated bar, in the order the approved mockups draw them
 * (data/ui-layout-plan/explainer-final.html: `nav() + timelineRow() +
 * bar()`): MENU, then TIMELINE, then BAR.
 *
 * It exists because the order itself drifted and nothing caught it: the
 * live app rendered the bar BEFORE the strip, while the design-fidelity
 * harness hand-rolled the mockup's own order — so the gate was proving a
 * composition the app did not have. This is now the ONE composition both
 * use (App.tsx for the real app, harness/fidelity.tsx for the gate), so
 * the next change to the order is caught by the pair images rather than
 * by someone noticing months later. "A gate you MODEL is a gate no proof
 * exercises" — AGENTS.md's own lesson, one layer up.
 *
 * Deliberately NOT in here: the testing bar and the released-room banner
 * (RoomOwnershipBar). Both are exceptional, full-width states that the
 * mockups never draw, and the testing bar's own ask is that it sit above
 * everything on every route — App.tsx keeps both, in their own places. */
import NavBar from '../nav/NavBar';
import RoomControlsBar from './RoomControlsBar';
import SongStrip from './SongStrip';
import TopBarStrip from './TopBarStrip';

export default function AppChrome({ showSongStrip = true, showNav = true }: {
  /** Home and the Timeline page carry their own editable copy of the
   * timeline (plan §13 decision 5), so the global one is hidden there. */
  showSongStrip?: boolean;
  /** The kiosk has no Spectra menu — Home Assistant provides the
   * navigation, and no menu means no way to wander off into a setup page
   * from the wall (kiosk/KioskPage.tsx's own docstring). */
  showNav?: boolean;
}) {
  return (
    <>
      {showNav && <NavBar />}
      {showSongStrip && <SongStrip />}
      {/* ONE BAR (UI declutter plan §3): RoomControlsBar and TopBarStrip
        * each still own their own state/logic, but `display: contents` on
        * both of their root divs (tokens.css) lets their children act as
        * direct flex items of `.one-bar` — one visual row, explicit
        * `order` per occupant (tokens.css) rather than a DOM rewrite of
        * either component. */}
      <div className="one-bar">
        <RoomControlsBar />
        <TopBarStrip />
      </div>
    </>
  );
}
