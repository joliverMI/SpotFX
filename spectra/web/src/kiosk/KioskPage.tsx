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
 * NOW THE CONSOLIDATED ONE BAR (fixed 2026-10-14, spotfx-deploy-423
 * finding B): this file's own header used to predict this swap and
 * nothing did it — `<RoomControlsBar />`/`<TopBarStrip />` rendered as
 * bare siblings here, so the `.one-bar >` scoping in tokens.css never
 * applied and the kiosk kept the OLD two-strip layout (~170px of the
 * 424px usable) even after the rest of the app moved to one line. Wrap
 * them the same way App.tsx does.
 *
 * 800px is inside tokens.css's "deliberate two rows" band (521-1100px,
 * the Admiral's own decision, 2026-10-14, superseding an earlier attempt
 * at this width that shed the device preview and several bar controls
 * outright to force one line — "do not shed swatches or hide controls to
 * force one line"), so the kiosk's bar is TWO rows, like the 1024 tablet,
 * with nothing hidden: row 1 is house/display mode/Hue Hold/Scenes/
 * Colour, row 2 is Energy+Mark/Light Show/preview/⚠/Release — see
 * tokens.css's own `.one-bar::before` rule for the mechanism. */
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
      <div className="one-bar">
        <RoomControlsBar />
        <TopBarStrip />
      </div>
      <main className="kiosk-main">
        <HomePage showAudioShape={KIOSK_SHOW_AUDIO_SHAPE} />
      </main>
    </div>
  );
}
