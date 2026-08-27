/** The shared scrub RULER for every SPECTRA preview (2026-08-27,
 * fm/flare-preview-offsets-everywhere).
 *
 * Extracted from FlarePreviewOverlay's own inline SVG so the transition
 * and drop-sequence previews draw the SAME instrument rather than three
 * hand-rolled ones that could drift in what a marker means. It draws only
 * what it is handed: bands (a span of time — a crossfade, a ramp, a hang),
 * marks (a fixed computed moment — an anchor, a start, an end, a phase
 * fire), one draggable TRIGGER mark, and the playhead.
 *
 * IT COMPUTES NO TIME OF ITS OWN. Every `at_s`/`from_s`/`to_s` it receives
 * was computed server-side; this component only maps seconds to pixels.
 * That is the rule the whole preview system rests on — the drawing and the
 * firing must never be able to disagree about a moment, which is exactly
 * the defect that started it. */
import { useRef } from 'react';

export interface RulerBand {
  from_s: number;
  to_s: number;
  label?: string;
  tone?: 'accent' | 'muted';
}

export interface RulerMark {
  at_s: number;
  label: string;
  tone?: 'accent' | 'muted' | 'hot';
  dashed?: boolean;
}

const PAD_X = 16;
const RULER_W = 680;
const RULER_H = 108;

function tickStep(durationS: number): number {
  if (durationS <= 8) return 1;
  if (durationS <= 20) return 2;
  return 5;
}

const TONE: Record<string, string> = {
  accent: 'var(--accent)',
  muted: 'var(--text-muted)',
  hot: '#ff5a3c',
};

export default function PreviewRuler({
  durationS, playheadS, bands, marks, triggerMarkS,
  onScrub, onTriggerDrag, onTriggerDragEnd,
}: {
  durationS: number;
  playheadS: number;
  bands: RulerBand[];
  marks: RulerMark[];
  /** null = this preview has no draggable mark (the drop sequence: a
   * band's offset is an aggregate over its kinds, so a drag would have to
   * pick one to write to — see PhasePreviewMark.trigger_offset_ms). */
  triggerMarkS: number | null;
  onScrub: (s: number) => void;
  onTriggerDrag?: (s: number) => void;
  onTriggerDragEnd?: (s: number) => void;
}) {
  const svgRef = useRef<SVGSVGElement | null>(null);

  const xToS = (clientX: number): number => {
    const svg = svgRef.current;
    if (!svg) return 0;
    const rect = svg.getBoundingClientRect();
    const frac = (clientX - rect.left - PAD_X) / (rect.width - 2 * PAD_X);
    return Math.max(0, Math.min(durationS, frac * durationS));
  };
  const sToX = (s: number): number =>
    PAD_X + (s / durationS) * (RULER_W - 2 * PAD_X);

  const scrub = (e: React.PointerEvent) => {
    (e.currentTarget as Element).setPointerCapture(e.pointerId);
    onScrub(xToS(e.clientX));
    const move = (ev: PointerEvent) => onScrub(xToS(ev.clientX));
    const up = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  };

  const dragTrigger = (e: React.PointerEvent) => {
    e.stopPropagation();
    (e.currentTarget as Element).setPointerCapture(e.pointerId);
    const move = (ev: PointerEvent) => onTriggerDrag?.(xToS(ev.clientX));
    const up = (ev: PointerEvent) => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
      onTriggerDragEnd?.(xToS(ev.clientX));
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  };

  const ticks: number[] = [];
  for (let t = 0; t <= durationS + 1e-6; t += tickStep(durationS)) ticks.push(t);

  return (
    <svg ref={svgRef} viewBox={`0 0 ${RULER_W} ${RULER_H}`}
      style={{ width: '100%', height: RULER_H, touchAction: 'none', cursor: 'pointer' }}
      onPointerDown={scrub}>
      <rect x={0} y={0} width={RULER_W} height={RULER_H} fill="var(--panel-bg, #1a1024)" />
      {bands.map((b, i) => (
        <g key={`b${i}`}>
          <rect x={sToX(b.from_s)} y={22}
            width={Math.max(1, sToX(b.to_s) - sToX(b.from_s))} height={RULER_H - 46}
            fill={TONE[b.tone ?? 'accent']} opacity={b.tone === 'muted' ? 0.1 : 0.18} />
          {b.label && (
            <text x={(sToX(b.from_s) + sToX(b.to_s)) / 2} y={RULER_H - 30} fontSize={9}
              fill={TONE[b.tone ?? 'accent']} textAnchor="middle" opacity={0.9}>
              {b.label}
            </text>
          )}
        </g>
      ))}
      {ticks.map((t) => (
        <g key={`t${t}`}>
          <line x1={sToX(t)} x2={sToX(t)} y1={RULER_H - 18} y2={RULER_H - 12}
            stroke="var(--text-muted)" />
          <text x={sToX(t)} y={RULER_H - 2} fontSize={9} fill="var(--text-muted)"
            textAnchor="middle">{t}s</text>
        </g>
      ))}
      {marks.map((m, i) => (
        <g key={`m${i}`}>
          <line x1={sToX(m.at_s)} x2={sToX(m.at_s)} y1={16} y2={RULER_H - 20}
            stroke={TONE[m.tone ?? 'accent']} strokeWidth={2}
            strokeDasharray={m.dashed ? '3,2' : undefined} />
          <text x={sToX(m.at_s)} y={12} fontSize={9} fill={TONE[m.tone ?? 'accent']}
            textAnchor="middle">{m.label}</text>
        </g>
      ))}
      <line x1={sToX(playheadS)} x2={sToX(playheadS)} y1={0} y2={RULER_H}
        stroke="#fff" strokeWidth={1.5} opacity={0.9} />
      {triggerMarkS != null && (
        <g onPointerDown={onTriggerDrag ? dragTrigger : undefined}
          style={{ cursor: onTriggerDrag ? 'ew-resize' : 'default' }}>
          <line x1={sToX(triggerMarkS)} x2={sToX(triggerMarkS)} y1={0} y2={RULER_H}
            stroke={TONE.hot} strokeWidth={2} />
          <polygon points={`${sToX(triggerMarkS) - 6},0 ${sToX(triggerMarkS) + 6},0 ${sToX(triggerMarkS)},10`}
            fill={TONE.hot} />
          <text x={sToX(triggerMarkS)} y={RULER_H - 24} fontSize={9} fill={TONE.hot}
            textAnchor="middle">trigger</text>
        </g>
      )}
    </svg>
  );
}
