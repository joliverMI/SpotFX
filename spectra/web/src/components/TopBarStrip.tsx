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
 * preview is expanded, a second element with `flex: 1 0 100%`. Because a
 * Fragment's children land directly as flex items of THIS div, that
 * second element always wraps onto its own full-width line below every
 * other occupant here — see DevicePreviewStrip.tsx's own module docstring
 * ("NO TEXT IN THE EXPANDED STAGE, AND IT NOW LANDS BELOW...") before
 * changing this element to anything other than a flex-wrap container, or
 * that mechanism breaks. */
import DevicePreviewStrip from './DevicePreviewStrip';
import ModeChip from './ModeChip';
import IntensityMarkControl from './IntensityMarkControl';
import LiveEnergyReadout from './LiveEnergyReadout';
import LightShowStrip from './LightShowStrip';

export default function TopBarStrip() {
  return (
    <div className="top-bar-strip">
      {/* House lighting's mode — FIRST, the resting state every page sits on. */}
      <ModeChip />
      <LiveEnergyReadout />
      <IntensityMarkControl />
      <LightShowStrip />
      <DevicePreviewStrip />
    </div>
  );
}
