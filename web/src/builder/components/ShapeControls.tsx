/** Band + librosa filter buttons and the intensity-bg toggle. Band buttons keep
 * the classic multi-gesture: click = fill toggle, right-click = avg-line
 * toggle, long-press (400ms) + vertical drag = per-band scale (log, ±100px =
 * ×2/÷2, snap 1.0). All state arrives via props (sticky at the page level). */
import { useRef } from 'react';
import type { ViewState } from '../canvas/frame';
import { INTENSITY_MODES, INTENSITY_MODE_LABELS, type IntensityBgMode } from '../canvas/frame';
import { SCALE_LABELS } from '../canvas/data';

type Band = 'total' | 'bass' | 'mid' | 'high';
const BANDS: Band[] = ['total', 'bass', 'mid', 'high'];

export default function ShapeControls({
  view,
  setFilters,
  setAvgFilters,
  setScales,
  setLibrosaFilter,
  setIntensityMode,
  hasLibrosa,
  hasIntensityCurve,
}: {
  view: ViewState;
  setFilters: (patch: Partial<ViewState['filters']>) => void;
  setAvgFilters: (patch: Partial<ViewState['avgFilters']>) => void;
  setScales: (band: Band, value: number) => void;
  setLibrosaFilter: (key: keyof ViewState['librosaFilters'], value: boolean) => void;
  setIntensityMode: (v: IntensityBgMode) => void;
  hasLibrosa: boolean;
  hasIntensityCurve: boolean;
}) {
  const gesture = useRef<{
    band: Band; startY: number; startScale: number; timer: ReturnType<typeof setTimeout> | null;
    scaling: boolean; moved: boolean;
  } | null>(null);

  const onBandPointerDown = (band: Band) => (ev: React.PointerEvent) => {
    if (ev.button !== 0) return;
    (ev.target as HTMLElement).setPointerCapture(ev.pointerId);
    gesture.current = {
      band, startY: ev.clientY, startScale: view.scales[band],
      timer: setTimeout(() => { if (gesture.current) gesture.current.scaling = true; }, 400),
      scaling: false, moved: false,
    };
  };
  const onBandPointerMove = (ev: React.PointerEvent) => {
    const g = gesture.current;
    if (!g?.scaling) return;
    g.moved = true;
    const dy = g.startY - ev.clientY; // up = louder
    let scale = g.startScale * Math.pow(2, dy / 100);
    if (Math.abs(scale - 1) < 0.06) scale = 1; // snap
    setScales(g.band, Math.max(0.1, Math.min(8, Number(scale.toFixed(3)))));
  };
  const onBandPointerUp = (band: Band) => () => {
    const g = gesture.current;
    if (g?.timer) clearTimeout(g.timer);
    if (g && !g.scaling) setFilters({ [band]: !view.filters[band] } as Partial<ViewState['filters']>);
    gesture.current = null;
  };

  const bandBtn = (band: Band) => {
    const on = view.filters[band];
    const scaled = view.scales[band] !== 1;
    return (
      <button
        key={band}
        className={`chip filter ${on ? 'active' : ''}`}
        style={{ userSelect: 'none', touchAction: 'none' }}
        title={`${SCALE_LABELS[band]} — click: fill · right-click: avg line · hold+drag: scale (${view.scales[band].toFixed(2)}×)`}
        onPointerDown={onBandPointerDown(band)}
        onPointerMove={onBandPointerMove}
        onPointerUp={onBandPointerUp(band)}
        onContextMenu={(e) => {
          e.preventDefault();
          setAvgFilters({ [band]: !view.avgFilters[band] } as Partial<ViewState['avgFilters']>);
        }}
      >
        {SCALE_LABELS[band]}
        {view.avgFilters[band] && on ? ' ~' : ''}
        {scaled ? ` ${view.scales[band].toFixed(1)}×` : ''}
      </button>
    );
  };

  const LIBROSA_KEYS: (keyof ViewState['librosaFilters'])[] = [
    'sections', 'beats', 'onsets', 'harmonic', 'bass', 'snare', 'mfcc',
  ];

  return (
    <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center', marginTop: 8 }}>
      {BANDS.map(bandBtn)}
      <button
        className={`chip filter ${view.filters.marks ? 'active' : ''}`}
        onClick={() => setFilters({ marks: !view.filters.marks })}
      >
        Marks
      </button>
      <button
        className={`chip filter ${view.intensityMode !== 'off' ? 'active' : ''}`}
        title="Intensity background — click: on/off · scroll over the button: pick source (Total RMS / Bass RMS / Section energy / Trigger intensity)"
        onClick={() => setIntensityMode(view.intensityMode === 'off'
          ? (hasIntensityCurve ? 'total' : 'triggers') : 'off')}
        onWheel={(e) => {
          e.preventDefault();
          const cur = INTENSITY_MODES.indexOf(view.intensityMode);
          const dir = e.deltaY > 0 ? 1 : -1;
          let next = (cur + dir + INTENSITY_MODES.length) % INTENSITY_MODES.length;
          if (INTENSITY_MODES[next] === 'off') {
            next = (next + dir + INTENSITY_MODES.length) % INTENSITY_MODES.length;
          }
          setIntensityMode(INTENSITY_MODES[next]);
        }}
      >
        ⚡ {INTENSITY_MODE_LABELS[view.intensityMode]}
      </button>
      {hasLibrosa && (
        <>
          <span style={{ color: 'var(--text-muted)', fontSize: 11, marginLeft: 8 }}>librosa</span>
          {LIBROSA_KEYS.map((k) => (
            <button
              key={k}
              className={`chip filter ${view.librosaFilters[k] ? 'active' : ''}`}
              onClick={() => setLibrosaFilter(k, !view.librosaFilters[k])}
            >
              {k}
            </button>
          ))}
        </>
      )}
    </div>
  );
}
