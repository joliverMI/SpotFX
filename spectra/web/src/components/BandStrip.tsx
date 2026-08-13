/** BandStrip — the response tabs' graphical surface: intensity bands drawn
 * over the 0–1 axis (same SVG idiom as the CurveEditor). Drag a band's
 * edges to move its window, drag its gain handle vertically, double-click
 * a band to remove it, click an empty gap to add a band there. Everything
 * else about a band (curve, patches, class flags) renders below the strip;
 * param patches stay agent-only with a visible indicator. */
import { useRef, useState } from 'react';
import type { FlareBand } from '../types';

const PAD = { left: 34, right: 10, top: 10, bottom: 22 };
const GAIN_MAX = 3;

const CURVE_COLOR: Record<FlareBand['curve'], string> = {
  linear: 'var(--accent)',
  ease_in: '#8b5cf6',
  ease_out: '#c084fc',
  pulse: 'var(--accent2)',
};

export default function BandStrip({
  bands,
  onChange,
  width = 560,
  height = 150,
}: {
  bands: FlareBand[];
  onChange: (bands: FlareBand[]) => void;
  width?: number;
  height?: number;
}) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [drag, setDrag] = useState<{ idx: number; part: 'min' | 'max' | 'gain' } | null>(null);

  const plotW = width - PAD.left - PAD.right;
  const plotH = height - PAD.top - PAD.bottom;
  const px = (x: number) => PAD.left + x * plotW;
  const py = (g: number) => PAD.top + (1 - Math.min(g, GAIN_MAX) / GAIN_MAX) * plotH;

  const toX = (e: { clientX: number }): number => {
    const rect = svgRef.current!.getBoundingClientRect();
    const sx = ((e.clientX - rect.left) * (width / rect.width) - PAD.left) / plotW;
    return Math.min(1, Math.max(0, sx));
  };
  const toGain = (e: { clientY: number }): number => {
    const rect = svgRef.current!.getBoundingClientRect();
    const sy = 1 - ((e.clientY - rect.top) * (height / rect.height) - PAD.top) / plotH;
    return Math.round(Math.min(GAIN_MAX, Math.max(0, sy * GAIN_MAX)) * 20) / 20;
  };

  const setBand = (i: number, patch: Partial<FlareBand>) =>
    onChange(bands.map((b, j) => (j === i ? { ...b, ...patch } : b)));

  const move = (e: React.PointerEvent) => {
    if (!drag) return;
    const { idx, part } = drag;
    const sorted = [...bands].map((b, i) => ({ b, i })).sort((a, z) => a.b.intensity_min - z.b.intensity_min);
    const pos = sorted.findIndex((s) => s.i === idx);
    if (part === 'gain') {
      setBand(idx, { gain: toGain(e) });
      return;
    }
    const x = Math.round(toX(e) * 100) / 100;
    const band = bands[idx];
    if (part === 'min') {
      const lo = pos > 0 ? sorted[pos - 1].b.intensity_max : 0;
      setBand(idx, { intensity_min: Math.min(Math.max(x, lo), band.intensity_max - 0.01) });
    } else {
      const hi = pos < sorted.length - 1 ? sorted[pos + 1].b.intensity_min : 1;
      setBand(idx, { intensity_max: Math.max(Math.min(x, hi), band.intensity_min + 0.01) });
    }
  };

  const addAt = (e: React.MouseEvent) => {
    if (drag) return;
    const x = toX(e);
    if (bands.some((b) => x >= b.intensity_min && x < b.intensity_max)) return;
    // The empty gap containing x becomes the new band.
    let lo = 0;
    let hi = 1;
    for (const b of bands) {
      if (b.intensity_max <= x) lo = Math.max(lo, b.intensity_max);
      if (b.intensity_min > x) hi = Math.min(hi, b.intensity_min);
    }
    onChange([...bands, {
      intensity_min: Math.round(lo * 100) / 100,
      intensity_max: Math.round(hi * 100) / 100,
      curve: 'linear', gain: 1, param_patch: {},
    }]);
  };

  return (
    <svg
      ref={svgRef}
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      style={{ maxWidth: '100%', touchAction: 'none', cursor: 'crosshair', userSelect: 'none' }}
      onClick={addAt}
      onPointerMove={move}
      onPointerUp={() => setDrag(null)}
    >
      {[0, 0.25, 0.5, 0.75, 1].map((gx) => (
        <g key={gx}>
          <line x1={px(gx)} y1={PAD.top} x2={px(gx)} y2={PAD.top + plotH}
            stroke="var(--border)" strokeWidth={gx === 0 || gx === 1 ? 1.5 : 0.5} />
          <text x={px(gx)} y={height - 6} textAnchor="middle"
            fontSize={10} fill="var(--text-muted)">{gx}</text>
        </g>
      ))}
      <line x1={px(0)} y1={py(1)} x2={px(1)} y2={py(1)}
        stroke="var(--border)" strokeWidth={0.5} strokeDasharray="4 3" />
      {[0, 1, GAIN_MAX].map((gy) => (
        <text key={gy} x={PAD.left - 6} y={py(gy) + 3} textAnchor="end"
          fontSize={10} fill="var(--text-muted)">{gy}×</text>
      ))}
      <line x1={px(0)} y1={PAD.top + plotH} x2={px(1)} y2={PAD.top + plotH}
        stroke="var(--border)" strokeWidth={1.5} />

      {bands.map((b, i) => {
        const x0 = px(b.intensity_min);
        const x1 = px(b.intensity_max);
        const gy = py(b.gain);
        const color = CURVE_COLOR[b.curve];
        const patched = Object.keys(b.param_patch ?? {}).length > 0;
        return (
          <g key={i}>
            <rect x={x0} y={gy} width={x1 - x0} height={PAD.top + plotH - gy}
              fill={color} opacity={0.22}
              onClick={(e) => e.stopPropagation()}
              onDoubleClick={(e) => {
                e.stopPropagation();
                onChange(bands.filter((_, j) => j !== i));
              }}>
              <title>{`[${b.intensity_min}–${b.intensity_max}) ${b.curve} ×${b.gain}${patched ? ` — ${Object.keys(b.param_patch).length} patched param(s), agent-managed` : ''}\ndouble-click to remove`}</title>
            </rect>
            <line x1={x0} y1={gy} x2={x1} y2={gy} stroke={color} strokeWidth={2.5} />
            {/* edge handles */}
            {(['min', 'max'] as const).map((part) => (
              <line key={part}
                x1={part === 'min' ? x0 : x1} y1={PAD.top}
                x2={part === 'min' ? x0 : x1} y2={PAD.top + plotH}
                stroke={color} strokeWidth={8} opacity={0.001}
                style={{ cursor: 'ew-resize' }}
                onClick={(e) => e.stopPropagation()}
                onPointerDown={(e) => {
                  e.stopPropagation();
                  (e.target as Element).setPointerCapture?.(e.pointerId);
                  setDrag({ idx: i, part });
                }} />
            ))}
            {(['min', 'max'] as const).map((part) => (
              <line key={`v-${part}`}
                x1={part === 'min' ? x0 : x1} y1={gy}
                x2={part === 'min' ? x0 : x1} y2={PAD.top + plotH}
                stroke={color} strokeWidth={1.5} />
            ))}
            {/* gain handle */}
            <circle cx={(x0 + x1) / 2} cy={gy} r={drag?.idx === i && drag.part === 'gain' ? 8 : 6}
              fill={color} stroke="var(--surface2)" strokeWidth={1.5}
              style={{ cursor: 'ns-resize' }}
              onClick={(e) => e.stopPropagation()}
              onPointerDown={(e) => {
                e.stopPropagation();
                (e.target as Element).setPointerCapture?.(e.pointerId);
                setDrag({ idx: i, part: 'gain' });
              }}>
              <title>{`gain ×${b.gain} — drag vertically`}</title>
            </circle>
            {patched && (
              <text x={(x0 + x1) / 2} y={PAD.top + plotH - 5} textAnchor="middle"
                fontSize={11} fill="var(--text)">⚙</text>
            )}
          </g>
        );
      })}
    </svg>
  );
}
