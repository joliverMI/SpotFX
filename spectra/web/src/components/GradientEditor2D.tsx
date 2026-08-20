/** The two-dimensional drift gradient's editor — his own words: "The UI
 * should be very similar to the current gradient picker, just make it a
 * square." Reuses ColorGradientPicker VERBATIM for each edge (top = y=1 /
 * high intensity, bottom = y=0 / low intensity) rather than inventing a new
 * colour-stop-editing widget: each edge IS the exact same gradient bar he
 * already uses everywhere else in the app, and the square preview beneath
 * shows the bilinear fill between the two. Explicitly NOT a rotation
 * control (his own pre-emption) — there is no angle/rotation input here. */
import ColorGradientPicker from './ColorGradientPicker';
import GradientSquarePreview from './GradientSquarePreview';

export type XMode = 'loop' | 'bounce';

export default function GradientEditor2D({
  top, bottom, xMode, onChangeTop, onChangeBottom, onChangeXMode,
}: {
  top: string;
  bottom: string;
  xMode: XMode;
  onChangeTop: (v: string) => void;
  onChangeBottom: (v: string) => void;
  onChangeXMode: (v: XMode) => void;
}) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ fontSize: 11, color: 'var(--text-muted)', width: 70 }}>
          Top (high ⚡)
        </span>
        <ColorGradientPicker value={top} onChange={onChangeTop} gradient
          swatchWidth="100%" swatchHeight={22} title="Top edge — high intensity" />
      </div>

      <GradientSquarePreview top={top} bottom={bottom} size={160}
        style={{ alignSelf: 'center', margin: '4px 0' }} />

      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ fontSize: 11, color: 'var(--text-muted)', width: 70 }}>
          Bottom (low ⚡)
        </span>
        <ColorGradientPicker value={bottom} onChange={onChangeBottom} gradient
          swatchWidth="100%" swatchHeight={22} title="Bottom edge — low intensity" />
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 4 }}>
        <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>Along time (x-axis):</span>
        <button type="button" style={{ fontSize: 11, padding: '2px 8px',
                 borderColor: xMode === 'loop' ? 'var(--accent)' : undefined }}
          onClick={() => onChangeXMode('loop')}>↻ Loop</button>
        <button type="button" style={{ fontSize: 11, padding: '2px 8px',
                 borderColor: xMode === 'bounce' ? 'var(--accent)' : undefined }}
          onClick={() => onChangeXMode('bounce')}>⇄ Bounce</button>
      </div>
    </div>
  );
}
