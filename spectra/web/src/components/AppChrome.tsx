/** THE CHROME, IN ONE PLACE — the menu, the one consolidated bar and the
 * global song timeline, plus the page body as its children.
 *
 * MENU, THEN BAR, THEN TIMELINE (the Admiral, 2026-10-15, verbatim: "move
 * the timeline below the toolbar (with all the buttons and things like
 * scene, colour, mark, etc)"). This is an explicit, deliberate DEPARTURE
 * from the approved mockups, which draw `nav() + timelineRow() + bar()`
 * — his own later word on his own design, which outranks the artifact.
 * `scripts/check_ui_fidelity.py`'s chrome-order assertion encodes this
 * order, not the artifact's, and says so.
 *
 * It exists because the order itself drifted once and nothing caught it:
 * the live app rendered the bar BEFORE the strip, while the design-
 * fidelity harness hand-rolled the mockup's own order — so the gate was
 * proving a composition the app did not have. This is the ONE composition
 * the app (App.tsx), the kiosk (kiosk/KioskPage.tsx) and the gate
 * (harness/fidelity.tsx) all render, so the next change to the order is
 * caught by the pair images rather than by someone noticing months later.
 * "A gate you MODEL is a gate no proof exercises" — AGENTS.md's own
 * lesson, one layer up.
 *
 * IT TAKES THE PAGE BODY AS CHILDREN so the shared song-timeline view
 * state (components/songTimelineView.tsx — the one window, the one set of
 * marker filters, the one view history) has exactly ONE mount point
 * covering BOTH the timeline row and whatever page is driving it. Home's
 * audio shape sits inside `<main>`, a DOM sibling of this chrome, and
 * drives the timeline's window; a provider each caller had to remember to
 * wrap would be three mount points to drift apart.
 *
 * Deliberately NOT in here: the testing bar and the released-room banner
 * (RoomOwnershipBar). Both are exceptional, full-width states that the
 * mockups never draw, and the testing bar's own ask is that it sit above
 * everything on every route — App.tsx keeps both, in their own places. */
import type { ReactNode } from 'react';
import NavBar from '../nav/NavBar';
import RoomControlsBar from './RoomControlsBar';
import SongStrip from './SongStrip';
import TopBarStrip from './TopBarStrip';
import { SongTimelineViewProvider } from './songTimelineView';

/** WHERE THE GLOBAL TIMELINE IS DRAWN — the one definition, so App.tsx,
 * the kiosk and the design-fidelity harness can never disagree about it
 * (they did once: the harness rendered it on Home, where the app did
 * not, and the pair image showed a row the real app never drew there).
 *
 * HOME NOW SHOWS IT (the Admiral, 2026-10-15) — it is the same row in the
 * same place on every route, which is the whole point of his ask: it used
 * to jump from the chrome down the page on Home, because Home drew its
 * own copy. Home still EDITS it (the draggable window sets what Home's
 * audio shape shows) through the shared view state above; it no longer
 * draws a second one.
 *
 * `/timeline` keeps its own full editing toolset and so still hides it;
 * the Live pop-out has no chrome at all and is handled before this.
 *
 * Pure and exported so a check can drive the table with no DOM. */
export function showsSongStrip(pathname: string): boolean {
  return pathname !== '/timeline';
}

export default function AppChrome({ showSongStrip = true, showNav = true, children }: {
  /** The Timeline page carries its own editable copy of the timeline, so
   * the global one is hidden there (see `showsSongStrip`). */
  showSongStrip?: boolean;
  /** The kiosk has no Spectra menu — Home Assistant provides the
   * navigation, and no menu means no way to wander off into a setup page
   * from the wall (kiosk/KioskPage.tsx's own docstring). */
  showNav?: boolean;
  /** The page body (and anything else that belongs under the chrome's
   * shared song-timeline view state). */
  children?: ReactNode;
}) {
  return (
    <SongTimelineViewProvider>
      {showNav && <NavBar />}
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
      {showSongStrip && <SongStrip />}
      {children}
    </SongTimelineViewProvider>
  );
}
