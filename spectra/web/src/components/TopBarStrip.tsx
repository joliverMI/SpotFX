/** Shared top-bar strip — mounted once in App.tsx, next to
 * RoomControlsBar, visible on every SPECTRA route with no per-page
 * wiring (same "one global mount point" shape RoomControlsBar itself
 * proves). Occupants: the live energy readout, and the device-preview
 * strip (data/spectra-device-preview-plan/report.md §5) — this container
 * is deliberately generic rather than energy-specific so a later addition
 * doesn't require moving or restructuring this mount point. */
import DevicePreviewStrip from './DevicePreviewStrip';
import LiveEnergyReadout from './LiveEnergyReadout';

export default function TopBarStrip() {
  return (
    <div className="top-bar-strip">
      <LiveEnergyReadout />
      <DevicePreviewStrip />
    </div>
  );
}
