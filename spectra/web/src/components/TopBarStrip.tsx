/** Shared top-bar strip — mounted once in App.tsx, next to
 * RoomControlsBar, visible on every SPECTRA route with no per-page
 * wiring (same "one global mount point" shape RoomControlsBar itself
 * proves). Occupants: the live energy readout, the per-track intensity
 * mark (the live per-moment number vs. the per-song factor that scales
 * it — see IntensityMarkControl.tsx), and the device-preview strip
 * (data/spectra-device-preview-plan/report.md §5) — this container is
 * deliberately generic rather than energy-specific so a later addition
 * doesn't require moving or restructuring this mount point.
 *
 * `.top-bar-strip` is `display: flex; flex-wrap: wrap;` — load-bearing for
 * `<DevicePreviewStrip />`, which renders TWO top-level siblings (a
 * Fragment) rather than one: its own controls plus, only while its
 * preview is expanded, a second element with `flex: 1 0 100%`. That keeps
 * the wrap working for any STANDALONE render of this component (outside
 * `.one-bar`, e.g. an isolated test mount). Inside the app, though, this
 * div is itself `display: contents` under `.one-bar` (App.tsx/tokens.css),
 * which erases its own box — so in the live app the actual wrap-to-a-new-
 * line behaviour is `.one-bar:has(.device-preview-expanded-row)`
 * (tokens.css), not this rule. See DevicePreviewStrip.tsx's own module
 * docstring ("NO TEXT IN THE EXPANDED STAGE, AND IT NOW LANDS BELOW...")
 * before changing either place. */
import DevicePreviewStrip from './DevicePreviewStrip';
import ModeChip from './ModeChip';
import EnergyBar from './EnergyBar';
import LightShowStrip from './LightShowStrip';
import SongNextBox, { useNextBoxInBar } from './SongNextBox';
import WarningChip from './WarningChip';
import { useUpcoming } from '../queries';
import { kindShown, useSongTimelineView } from './songTimelineView';

export default function TopBarStrip() {
  // THE NEXT-EVENT BOX JOINS ROW 2 AT <=1100px (his Q1 answer,
  // 2026-10-15): the timeline row's own 96px box squeezed the track
  // beside it at the 1024 tablet and the 800 wall kiosk, and the bar's
  // second row had width going spare. `useNextBoxInBar` is the one
  // predicate this and SongStrip both ask, so it is never in both places
  // and never in neither.
  const nextInBar = useNextBoxInBar();
  // THE SAME RESOLVED TRACK the global row reads (songTimelineView.tsx):
  // live, or the last one seen this session (his Q2 answer). Reading the
  // raw live bridge track here would make the box's two hosts disagree
  // the instant music stops — the row keeps counting down the last
  // song's own events while this copy would fall back to its idle state.
  const { track, filters } = useSongTimelineView();
  const uri = track?.uri ?? null;
  const { data: upcoming } = useUpcoming(nextInBar ? uri : null);
  const barEvents = (upcoming?.events ?? []).filter((e) => kindShown(e.kind, filters));

  return (
    <div className="top-bar-strip">
      {/* House lighting's mode — FIRST, the resting state every page sits on.
        * Visual position within the merged one-bar row is driven by CSS
        * `order` (tokens.css's `.one-bar .mode-chip` etc.), not DOM order —
        * see App.tsx's own comment on the `display: contents` merge. */}
      <ModeChip />
      <EnergyBar />
      {nextInBar && (
        <SongNextBox events={barEvents}
          durationMs={track?.duration_ms ?? 0} host="bar" />
      )}
      <LightShowStrip />
      {/* The mockup's fourth thin divider (`.sp .sepv`) — see tokens.css's
        * own `.one-bar-sep-*` block for why each one is named for the
        * `order` it is given rather than its DOM neighbour. */}
      <span className="one-bar-sep one-bar-sep-before-preview" aria-hidden />
      <DevicePreviewStrip />
      <span className="one-bar-spacer" aria-hidden />
      <WarningChip />
    </div>
  );
}
