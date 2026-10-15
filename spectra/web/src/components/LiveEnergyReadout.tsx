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
 * is display-only: no new backend surface.
 *
 * DRAWN AS A BORDERED 34px SLOT (design-fidelity pass, 2026-10-14 — the
 * approved mockup's own `.sp .en`: a bolt glyph in the warning colour, a
 * 6px purple→magenta meter, and a bold tabular value), replacing the
 * unboxed "⚡ Energy" emoji + text + its own ⓘ circle (audit B5). It also
 * OPENS MARK below desktop width, where the mockup hides the Mark box
 * (Q12's "folds INTO the Energy button") — see IntensityMarkControl.tsx's
 * own `compact` prop for that half. */
import Icon from './Icon';
import InfoTip from './InfoTip';
import { useEngineStatus } from '../queries';

export default function LiveEnergyReadout({ onOpenMark }: { onOpenMark?: () => void }) {
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
    <InfoTip
      topic="live-energy"
      text="The same number the engine's own automatic decisions read — raw section energy at the current playback position, 0.00 quietest to 1.00 loudest this song. Below desktop width, tapping it opens this song's intensity Mark."
    >
      <button type="button" className="energy-readout" title={title}
        data-mark-opener
        onClick={onOpenMark} aria-label={`Live section energy${intensity != null ? ` ${intensity.toFixed(2)}` : ' unavailable'}`}>
        <Icon name="bolt" size={14} className="energy-readout-bolt" />
        <span className="energy-meter">
          <span
            className="energy-meter-fill"
            style={{ width: intensity != null ? `${Math.round(intensity * 100)}%` : '0%' }}
          />
        </span>
        <span className="energy-readout-value tabular-nums">
          {intensity != null ? intensity.toFixed(2) : '—'}
        </span>
      </button>
    </InfoTip>
  );
}
