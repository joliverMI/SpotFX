/** Shared top-bar strip — mounted once in App.tsx, next to
 * RoomControlsBar, visible on every SPECTRA route with no per-page
 * wiring (same "one global mount point" shape RoomControlsBar itself
 * proves). First occupant: the live energy readout. The device-preview
 * strip planned in data/spectra-device-preview-plan/report.md §5 (not
 * yet authorised) is designed to mount here too, as a sibling, once
 * built — this container is deliberately generic rather than
 * energy-specific so that later addition doesn't require moving or
 * restructuring this mount point. */
import LiveEnergyReadout from './LiveEnergyReadout';

export default function TopBarStrip() {
  return (
    <div className="top-bar-strip">
      <LiveEnergyReadout />
    </div>
  );
}
