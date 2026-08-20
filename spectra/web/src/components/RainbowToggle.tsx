/** Rainbow select's per-card "rainbow" / "single" flag (owner ask
 * 2026-08-20, spectra/services/rainbow_select.py) — ENUMERATED, never
 * inferred from name. Sits on the same row as ModeAvailabilityToggle,
 * same fixed-size-toggle discipline (must not change size on tap — see
 * that component's own docstring for why). */
import { fixedSizeToggleStyle } from './fixedSizeToggleStyle';

const TOGGLE_WIDTH = 92;

export default function RainbowToggle({ value, onChange }: {
  value: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <button
      type="button"
      style={{
        ...fixedSizeToggleStyle(TOGGLE_WIDTH),
        color: value ? '#ff8a65' : 'var(--text-muted)',
        borderColor: value ? 'var(--accent)' : undefined,
      }}
      title={value
        ? 'Rainbow — only chosen above the room\'s rainbow select limit. Tap to make Single.'
        : 'Single — never chosen above the room\'s rainbow select limit. Tap to make Rainbow.'}
      onClick={() => onChange(!value)}
    >
      {value ? '🌈 Rainbow' : '⬤ Single'}
    </button>
  );
}
