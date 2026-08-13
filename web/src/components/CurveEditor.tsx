/** CurveEditor — the ONLY graphical weight surface (SPECTRA sequencing
 * design, interface split): a likelihood curve over intensity as draggable
 * points with straight lines between them. Click empty space to add a point,
 * drag to move (x is held between its neighbors; equal x = a step),
 * double-click to remove. The faint histogram underlay is the library's real
 * fire-intensity census — drag points where music actually happens.
 * Standalone and controlled: edits only the `points` prop via onChange. */
import { useRef, useState } from 'react';

export interface CurvePoint {
  x: number;
  y: number;
}

const PAD = { left: 34, right: 10, top: 10, bottom: 22 };

export default function CurveEditor({
  points,
  onChange,
  histogram,
  width = 520,
  height = 220,
}: {
  points: CurvePoint[];
  onChange: (points: CurvePoint[]) => void;
  /** Bin counts spanning intensity 0–1 left to right (honesty underlay). */
  histogram?: number[];
  width?: number;
  height?: number;
}) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [dragIdx, setDragIdx] = useState<number | null>(null);
  const dragMoved = useRef(false);

  const plotW = width - PAD.left - PAD.right;
  const plotH = height - PAD.top - PAD.bottom;
  const yMax = Math.max(1, ...points.map((p) => p.y));
  const px = (x: number) => PAD.left + x * plotW;
  const py = (y: number) => PAD.top + (1 - y / yMax) * plotH;

  const toData = (e: { clientX: number; clientY: number }): CurvePoint => {
    const rect = svgRef.current!.getBoundingClientRect();
    const sx = ((e.clientX - rect.left) * (width / rect.width) - PAD.left) / plotW;
    const sy = 1 - ((e.clientY - rect.top) * (height / rect.height) - PAD.top) / plotH;
    return { x: Math.min(1, Math.max(0, sx)), y: Math.max(0, Math.min(yMax, sy * yMax)) };
  };

  const addPoint = (e: React.MouseEvent) => {
    if (dragIdx !== null || dragMoved.current) {
      dragMoved.current = false;
      return;
    }
    const p = toData(e);
    const next = [...points, p].sort((a, b) => a.x - b.x);
    onChange(next);
  };

  const movePoint = (e: React.PointerEvent) => {
    if (dragIdx === null) return;
    dragMoved.current = true;
    const p = toData(e);
    const lo = dragIdx > 0 ? points[dragIdx - 1].x : 0;
    const hi = dragIdx < points.length - 1 ? points[dragIdx + 1].x : 1;
    onChange(points.map((q, i) =>
      i === dragIdx ? { x: Math.min(hi, Math.max(lo, p.x)), y: p.y } : q));
  };

  const removePoint = (i: number) => {
    if (points.length <= 1) return; // a curve keeps at least one point (≡ scalar weight)
    onChange(points.filter((_, j) => j !== i));
  };

  const histMax = histogram?.length ? Math.max(...histogram, 1) : 1;
  // Clamped-flat extension to the plot edges, then linear between points.
  const path = points.length
    ? `M ${px(0)} ${py(points[0].y)} ` +
      points.map((p) => `L ${px(p.x)} ${py(p.y)}`).join(' ') +
      ` L ${px(1)} ${py(points[points.length - 1].y)}`
    : '';

  return (
    <svg
      ref={svgRef}
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      style={{ maxWidth: '100%', touchAction: 'none', cursor: 'crosshair', userSelect: 'none' }}
      onClick={addPoint}
      onPointerMove={movePoint}
      onPointerUp={() => setDragIdx(null)}
    >
      {/* histogram underlay: where the library actually fires */}
      {histogram?.map((count, i) => {
        const barH = (count / histMax) * plotH * 0.85;
        return (
          <rect
            key={i}
            x={px(i / histogram.length)}
            y={PAD.top + plotH - barH}
            width={plotW / histogram.length}
            height={barH}
            fill="var(--text-muted)"
            opacity={0.18}
          />
        );
      })}

      {/* frame + gridlines */}
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
      {[0, 1, yMax].filter((v, i, a) => a.indexOf(v) === i).map((gy) => (
        <text key={gy} x={PAD.left - 6} y={py(gy) + 3} textAnchor="end"
          fontSize={10} fill="var(--text-muted)">{gy}</text>
      ))}
      <line x1={px(0)} y1={PAD.top + plotH} x2={px(1)} y2={PAD.top + plotH}
        stroke="var(--border)" strokeWidth={1.5} />

      {/* the curve: linear between points, clamped flat outside */}
      {path && <path d={path} fill="none" stroke="var(--accent2)" strokeWidth={2} />}

      {points.map((p, i) => (
        <circle
          key={i}
          cx={px(p.x)}
          cy={py(p.y)}
          r={dragIdx === i ? 8 : 6}
          fill="var(--accent2)"
          stroke="var(--surface2)"
          strokeWidth={1.5}
          style={{ cursor: 'grab' }}
          onClick={(e) => e.stopPropagation()}
          onDoubleClick={(e) => { e.stopPropagation(); removePoint(i); }}
          onPointerDown={(e) => {
            e.stopPropagation();
            (e.target as Element).setPointerCapture?.(e.pointerId);
            setDragIdx(i);
          }}
        >
          <title>{`(${p.x.toFixed(2)}, ${p.y.toFixed(2)}) — drag to move, double-click to remove`}</title>
        </circle>
      ))}
    </svg>
  );
}
