/** The per-track manual intensity mark (2026-08-15 ruling) — the one way
 * past the automatic 0.75 ceiling (spectra/services/intensity_scale.py's
 * combine_measured_and_scale docstring): "he marks the track; automatic
 * never does." Sibling of LiveEnergyReadout on the shared TopBarStrip —
 * that shows the live per-moment energy number, this shows the per-song
 * FACTOR that scales it (auto, always <=125%, or a manual mark up to
 * 200%). See help topic "intensity-mark".
 *
 * ONE FIXED 48px BOX, "MARK / 89%" (design-fidelity pass, 2026-10-14 —
 * the approved mockup's own `.sp .mark`), with every editable thing in a
 * panel it opens. Two audit items at once: B6 (the face was loose text
 * plus its own ⓘ circle, and below 1180px only the WORD was hidden,
 * leaving a dangling "ⓘ —" after the meter) and N2 (the face used to
 * change between "Mark —", "Mark 89%" and "Mark 89% [Clear]", shifting
 * everything after it — Clear now lives in the panel, so the face is one
 * size whatever the state).
 *
 * `compact` is the mockup's own fold: at <=1180px the Mark box is hidden
 * (`@container sp (max-width: 1180px) { .mark { display: none } }`) and
 * the Energy slot opens this panel instead — Q12, decided yes. The two
 * halves are wired by EnergyBar.tsx, which owns the open/closed state so
 * either control can open the one panel. */
import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import {
  useClearIntensityScaleMark, useEngineStatus, useIntensityScaleMark, useSetIntensityScaleMark,
} from '../queries';
import InfoTip from './InfoTip';

export default function IntensityMarkControl({
  open, onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { data: st } = useEngineStatus();
  const uri = st?.bridge.track?.uri ?? null;
  const { data: mark } = useIntensityScaleMark(uri);
  const setMark = useSetIntensityScaleMark(uri);
  const clearMark = useClearIntensityScaleMark(uri);
  const [draft, setDraft] = useState('');
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  const wrapRef = useRef<HTMLDivElement>(null);

  const isMarked = mark?.mark != null;
  const effectivePct = mark ? Math.round(mark.effective_factor * 100) : null;
  const autoPct = mark ? Math.round(mark.auto_factor * 100) : 100;
  const minPct = mark ? Math.round(mark.manual_min * 100) : 0;
  const maxPct = mark ? Math.round(mark.manual_max * 100) : 200;

  // Seed the draft from the live value every time the panel opens, so it
  // never shows a stale number from a previous song or a cancelled edit.
  useEffect(() => {
    if (open && mark) setDraft(String(isMarked ? Math.round((mark.mark as number) * 100) : autoPct));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, mark]);

  // The panel is a `position: fixed` PORTAL, placed off the control's own
  // rect — `.one-bar` is an `overflow-x: auto` scroll container, so an
  // absolutely-positioned panel inside it is clipped at the bar's own
  // bottom edge (the same reason TopBarGroupButton and InfoTip both
  // portal their panels; see TopBarGroupButton.tsx's docstring).
  useLayoutEffect(() => {
    if (!open) return;
    const rect = wrapRef.current?.getBoundingClientRect();
    if (!rect) return;
    const width = Math.min(240, window.innerWidth - 16);
    setPos({
      top: rect.bottom + 6,
      left: Math.max(8, Math.min(rect.left, window.innerWidth - 8 - width)),
    });
  }, [open]);

  useEffect(() => {
    if (!open) return undefined;
    const onDown = (e: MouseEvent) => {
      const t = e.target as Node;
      if (wrapRef.current?.contains(t)) return;
      if ((t as HTMLElement).closest?.('.intensity-mark-panel')) return;
      if ((t as HTMLElement).closest?.('[data-mark-opener]')) return;
      onOpenChange(false);
    };
    document.addEventListener('mousedown', onDown);
    return () => document.removeEventListener('mousedown', onDown);
  }, [open, onOpenChange]);

  const title = !uri || !mark
    ? 'No song playing — nothing to mark'
    : isMarked
      ? `Marked at ${Math.round((mark.mark as number) * 100)}% — this song's Energy can reach 1.0 (an unmarked song stops at 0.75). Automatic would be ${autoPct}%. Tap to change.`
      : `Automatic scale: ${autoPct}% (genre + bass). Energy on an unmarked song stops at 0.75. Tap to mark this track.`;

  const parsed = parseFloat(draft);
  const sliderPct = Number.isNaN(parsed) ? minPct : Math.max(minPct, Math.min(maxPct, parsed));

  return (
    <div className="intensity-mark-wrap" ref={wrapRef}>
      <InfoTip
        topic="intensity-mark"
        text="This song's Energy scale: Energy is each section's place on the song's own 0 to 1 scale x 0.8 x this Mark. An unmarked song stops at 0.75 Energy; marking it (up to 200%) is the one way past that."
      >
        <button
          type="button"
          className={`intensity-mark${isMarked ? ' intensity-mark-set' : ''}`}
          title={title}
          disabled={!uri || !mark}
          aria-label={`Energy Mark${effectivePct != null ? ` ${effectivePct}%` : ' unavailable'}`}
          onClick={() => onOpenChange(!open)}
        >
          <small>Mark</small>
          <span className="intensity-mark-value tabular-nums">
            {effectivePct != null ? `${effectivePct}%` : '—'}
          </span>
        </button>
      </InfoTip>
      {open && mark && pos && createPortal((
        <div className="intensity-mark-panel" role="dialog" aria-label="Energy Mark"
          style={{ top: pos.top, left: pos.left }}>
          <div className="intensity-mark-panel-row">
            <input
              type="range"
              className="intensity-mark-slider"
              step={1} min={minPct} max={maxPct}
              value={sliderPct}
              onChange={(e) => setDraft(e.target.value)}
            />
            <input
              type="number" step={1} min={minPct} max={maxPct}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              // eslint-disable-next-line jsx-a11y/no-autofocus
              autoFocus
            />
            <span>%</span>
          </div>
          <div className="intensity-mark-panel-row">
            <button type="button" onClick={() => {
              const pct = parseFloat(draft);
              if (!Number.isNaN(pct)) setMark.mutate(pct / 100);
              onOpenChange(false);
            }}>Save</button>
            <button type="button" onClick={() => onOpenChange(false)}>Cancel</button>
            {isMarked && (
              <button type="button" onClick={() => { clearMark.mutate(); onOpenChange(false); }}>
                Clear
              </button>
            )}
          </div>
          <span className="intensity-mark-panel-note">
            Automatic would be {autoPct}% (an unmarked song's Energy stops at 0.75).
          </span>
        </div>
      ), document.body)}
    </div>
  );
}
