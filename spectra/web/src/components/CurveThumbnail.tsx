/** CurveThumbnail — read-only snapshot of a likelihood curve for grid
 * pickers (curve chooser grid). Same clamped-flat-extension path math as
 * CurveEditor (px/py/yMax), just non-interactive and small, so a thumbnail
 * is a scaled-down render of the SAME shape the full editor draws — never a
 * separate approximation that could visually disagree with the real curve. */
import { memo } from 'react';
import type { CurvePoint } from './CurveEditor';

const PAD = { left: 3, right: 3, top: 3, bottom: 3 };

function CurveThumbnail({
  points,
  width = 96,
  height = 48,
  style,
}: {
  points: CurvePoint[];
  width?: number;
  height?: number;
  /** Merged onto the svg's own style — e.g. `maxWidth: '100%'` to shrink a
   * larger design-size thumbnail (the trigger-button use in
   * CurveAttachmentEditor) to fit a narrow phone width without cropping. */
  style?: React.CSSProperties;
}) {
  const plotW = width - PAD.left - PAD.right;
  const plotH = height - PAD.top - PAD.bottom;
  const yMax = Math.max(1, ...points.map((p) => p.y));
  const px = (x: number) => PAD.left + x * plotW;
  const py = (y: number) => PAD.top + (1 - y / yMax) * plotH;

  const path = points.length
    ? `M ${px(0)} ${py(points[0].y)} ` +
      points.map((p) => `L ${px(p.x)} ${py(p.y)}`).join(' ') +
      ` L ${px(1)} ${py(points[points.length - 1].y)}`
    : '';

  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} style={{ display: 'block', ...style }}>
      <line x1={px(0)} y1={py(1)} x2={px(1)} y2={py(1)}
        stroke="var(--border)" strokeWidth={0.5} strokeDasharray="3 2" />
      <line x1={px(0)} y1={PAD.top + plotH} x2={px(1)} y2={PAD.top + plotH}
        stroke="var(--border)" strokeWidth={1} />
      {path && <path d={path} fill="none" stroke="var(--accent2)" strokeWidth={1.5} />}
    </svg>
  );
}

export default memo(CurveThumbnail);
