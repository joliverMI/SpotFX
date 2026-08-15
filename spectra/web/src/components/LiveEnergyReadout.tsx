/** Live section-energy readout — the first occupant of the shared
 * TopBarStrip (see TopBarStrip.tsx). Shows the SAME number the engine's
 * automatic decisions read, not a display-only recomputation:
 * bridge.intensity() (spectra/services/bridge.py — raw librosa section
 * energy at the live playback position, clamped 0-1, no smoothing). That
 * callable is wired directly into the drift conductor (engine.py's
 * `intensity=lambda: bridge.intensity()`), the sequencer's default scene
 * pick (scene_sequencer._default_intensity), and automatic transition
 * fires (trigger_engine._default_transition_intensity) — the one number
 * this build found feeding every automatic, non-authored decision path.
 * Already on the wire via useEngineStatus() (bridge.intensity), so this
 * is display-only: no new backend surface. */
import HelpLink from '../help/HelpLink';
import { useEngineStatus } from '../queries';

export default function LiveEnergyReadout() {
  const { data: st } = useEngineStatus();
  const intensity = st?.bridge.intensity ?? null;
  const connected = st?.bridge.connected ?? false;
  const playing = st?.bridge.track?.is_playing ?? false;

  const title = intensity != null
    ? 'Live section energy at the current playback position — the same number the drift conductor, sequencer, and automatic scene/transition picks read (0.00 = quietest section, 1.00 = loudest, this song)'
    : !connected
      ? 'Bridge to spot-effects is down — no live energy signal (the engine holds 0.5 neutral)'
      : !playing
        ? 'Nothing playing — no live energy signal'
        : 'This song has no section analysis yet — no live energy signal (the engine holds 0.5 neutral)';

  return (
    <div className="energy-readout" title={title}>
      <span className="energy-readout-label">⚡ Energy</span>
      <span className="energy-meter">
        <span
          className="energy-meter-fill"
          style={{ width: intensity != null ? `${Math.round(intensity * 100)}%` : '0%' }}
        />
      </span>
      <span className="energy-readout-value">
        {intensity != null ? intensity.toFixed(2) : '—'}
      </span>
      <HelpLink topic="live-energy" />
    </div>
  );
}
