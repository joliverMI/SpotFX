/** The Sung words lane's one control. A lens on the page only: it changes
 * which words are drawn and scored here, stores nothing, and reaches nothing
 * in the show. */
import HelpLink from '../../help/HelpLink';
import { MAX_EMPHASIS_SENSITIVITY, MIN_EMPHASIS_SENSITIVITY } from '../lyricsLane';

export default function LyricsKnobs({
  sensitivity, onChange, defaultSensitivity, nEmphasized, nWords,
}: {
  sensitivity: number;
  onChange: (v: number) => void;
  defaultSensitivity: number;
  nEmphasized: number;
  nWords: number;
}) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 8 }}>
      <label htmlFor="testbed-emphasis-sensitivity" style={{ fontSize: 12, color: 'var(--text-muted)' }}>
        Sensitivity: {sensitivity.toFixed(2)}
      </label>
      <input
        id="testbed-emphasis-sensitivity"
        type="range"
        min={MIN_EMPHASIS_SENSITIVITY}
        max={MAX_EMPHASIS_SENSITIVITY}
        step={0.01}
        value={sensitivity}
        onChange={(e) => onChange(Number(e.target.value))}
        style={{ flex: 1, maxWidth: 220 }}
      />
      <span style={{ fontSize: 12, color: 'var(--text-muted)', fontVariantNumeric: 'tabular-nums' }}>
        {nEmphasized} of {nWords} words
      </span>
      {Math.abs(sensitivity - defaultSensitivity) > 1e-9 && (
        <button type="button" onClick={() => onChange(defaultSensitivity)} style={{ fontSize: 11 }}>
          Reset ({defaultSensitivity.toFixed(2)})
        </button>
      )}
      <HelpLink topic="testbed-lyrics" title="The Sung words lane" />
    </div>
  );
}
