/** The kiosk view (`/?kiosk=1`) — song-layout-plan, data/ui-layout-plan/
 * report.md's kiosk section: Spectra hosted inside a Home Assistant
 * dashboard tab. No Spectra menu (HA already provides navigation, and no
 * menu means no way to wander off into a setup page from the wall) —
 * just the one bar and Home (timeline, audio shape, quick runs), sized
 * for the wall kiosk and its touch-only input.
 *
 * Sizing is River's 2026-10-14 reply (kiosk/kioskConfig.ts is the one
 * place to change it when a real measurement differs): a Raspberry Pi
 * 7in touchscreen, 800x480 landscape, Home Assistant's own ~56px header
 * eating part of that, leaving ~800x424 usable. At that size the audio
 * shape is dropped (KIOSK_SHOW_AUDIO_SHAPE) rather than squeezed
 * illegible — bar + timeline + quick runs are the priority.
 *
 * Reuses today's existing top-bar components (RoomControlsBar/
 * TopBarStrip) rather than anticipating the parallel ui-build-bar task's
 * consolidated one-bar rebuild — once that lands, this file's own
 * header swaps to the new bar with no other change here. */
import { useEffect, useRef } from 'react';
import RoomControlsBar from '../components/RoomControlsBar';
import TopBarStrip from '../components/TopBarStrip';
import HomePage from '../home/HomePage';
import { applyKioskSizeVars, KIOSK_SHOW_AUDIO_SHAPE } from './kioskConfig';

export default function KioskPage() {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (ref.current) applyKioskSizeVars(ref.current);
  }, []);
  return (
    <div ref={ref} className="kiosk-page">
      <RoomControlsBar />
      <TopBarStrip />
      <main className="kiosk-main">
        <HomePage showAudioShape={KIOSK_SHOW_AUDIO_SHAPE} />
      </main>
    </div>
  );
}
