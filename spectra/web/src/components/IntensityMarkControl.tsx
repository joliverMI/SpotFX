/** The per-track manual intensity mark (2026-08-15 ruling) — the one way
 * past the automatic 0.75 ceiling (spectra/services/intensity_scale.py's
 * combine_measured_and_scale docstring): "he marks the track; automatic
 * never does." Sibling of LiveEnergyReadout on the shared TopBarStrip —
 * that shows the live per-moment energy number, this shows the per-song
 * FACTOR that scales it (auto, always <=125%, or a manual mark up to
 * 200%). See help topic "intensity-mark". */
import { useState } from 'react';
import HelpLink from '../help/HelpLink';
import {
  useClearIntensityScaleMark, useEngineStatus, useIntensityScaleMark, useSetIntensityScaleMark,
} from '../queries';

export default function IntensityMarkControl() {
  const { data: st } = useEngineStatus();
  const uri = st?.bridge.track?.uri ?? null;
  const { data: mark } = useIntensityScaleMark(uri);
  const setMark = useSetIntensityScaleMark(uri);
  const clearMark = useClearIntensityScaleMark(uri);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState('');

  if (!uri || !mark) {
    return (
      <div className="intensity-mark" title="No song playing — nothing to mark">
        <span className="intensity-mark-label">Mark</span>
        <span className="intensity-mark-value">—</span>
      </div>
    );
  }

  const isMarked = mark.mark != null;
  const effectivePct = Math.round(mark.effective_factor * 100);
  const autoPct = Math.round(mark.auto_factor * 100);
  const minPct = Math.round(mark.manual_min * 100);
  const maxPct = Math.round(mark.manual_max * 100);

  if (editing) {
    const parsed = parseFloat(draft);
    const sliderPct = Number.isNaN(parsed) ? minPct : Math.max(minPct, Math.min(maxPct, parsed));
    return (
      <div className="intensity-mark intensity-mark-editing">
        <span className="intensity-mark-label">Mark</span>
        <input
          type="range"
          className="intensity-mark-slider"
          step={1}
          min={minPct}
          max={maxPct}
          value={sliderPct}
          onChange={(e) => setDraft(e.target.value)}
        />
        <input
          type="number"
          step={1}
          min={minPct}
          max={maxPct}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          autoFocus
        />
        <span>%</span>
        <button
          onClick={() => {
            const pct = parseFloat(draft);
            if (!Number.isNaN(pct)) setMark.mutate(pct / 100);
            setEditing(false);
          }}
        >
          Save
        </button>
        <button onClick={() => setEditing(false)}>Cancel</button>
      </div>
    );
  }

  return (
    <div
      className={isMarked ? 'intensity-mark intensity-mark-set' : 'intensity-mark'}
      title={isMarked
        ? `Manually marked at ${Math.round((mark.mark as number) * 100)}% — the automatic 75% ceiling doesn't apply to this song. Automatic would be ${autoPct}%.`
        : `Automatic scale: ${autoPct}% (genre + bass, capped at a 75% delivered intensity). Mark this track to push it higher.`}
    >
      <span className="intensity-mark-label">Mark</span>
      <span className="intensity-mark-value">{effectivePct}%</span>
      <button
        className="intensity-mark-edit-btn"
        onClick={() => {
          setDraft(String(isMarked ? Math.round((mark.mark as number) * 100) : autoPct));
          setEditing(true);
        }}
      >
        {isMarked ? 'Edit' : 'Mark'}
      </button>
      {isMarked && (
        <button className="intensity-mark-clear-btn" onClick={() => clearMark.mutate()}>
          Clear
        </button>
      )}
      <HelpLink topic="intensity-mark" />
    </div>
  );
}
