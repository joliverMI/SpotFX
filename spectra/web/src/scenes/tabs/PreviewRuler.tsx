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
 * the defect that started it.
 *
 * THE DRAGGABLE DROP MARK (`dragMark`, 2026-10-12 — the drop-sequence
 * preview's red line, which he "cannot click it and drag it"; the view "is
 * pretty crowded and it's hard to click on anything", and it must work on a
 * tablet). Built for a crowded ruler and a finger:
 *   - a HANDLE LANE is added below the ruler and holds nothing but the grab
 *     tab, so the main target never shares space with a band label, a tick
 *     or another mark's label;
 *   - the line itself also grabs, through a modest invisible strip — wide
 *     enough to hit, narrow enough that a press beside it still scrubs (it
 *     steals nothing it isn't on top of);
 *   - it is drawn LAST, so it sits above every other layer, and while it is
 *     held it thickens, glows and shows its readout in a bubble at the top
 *     (the finger covers the handle);
 *   - the grab keeps the offset between finger and line for the whole
 *     gesture (no jump on the first move — ShowCueBar's grab-offset rule),
 *     follows ONLY the pointer that grabbed it (a resting palm cannot drive
 *     or end it — TimelineCanvas's per-pointer rule), and a pointercancel
 *     (the browser taking the touch) cancels rather than commits;
 *   - the SVG is `touch-action: none`, so the page never scrolls under a
 *     drag; the handle is a keyboard slider too (←/→, Shift = bigger step).
 * The ruler still computes no time: the caller turns the pointer's seconds
 * into whatever the drag writes (dropMarkDrag.ts). */
import { useRef, useState } from 'react';
import { PRE_DROP_COLOR } from '../../timeline/dropSequences';

export interface RulerBand {
  from_s: number;
  to_s: number;
  label?: string;
  tone?: 'accent' | 'muted';
}

export interface RulerMark {
  at_s: number;
  label: string;
  /** `predrop` = the pre-drop's own orange (the drop-sequence preview). */
  tone?: 'accent' | 'muted' | 'hot' | 'predrop';
  dashed?: boolean;
}

/** The draggable mark (see the module docstring). Every number is
 * caller-computed; the ruler only draws it and reports pointer seconds. */
export interface RulerDragMark {
  /** Where the line is drawn now (the live position while held). */
  at_s: number;
  label: string;
  /** The handle's own text, e.g. "−400 ms". */
  readout: string;
  /** Spoken value for the slider role, e.g. "400 ms early". */
  valueText: string;
  title: string;
  /** Drawn highlighted (a drag in progress). */
  active?: boolean;
  /** The pointer's ruler seconds, grab offset applied. */
  onDrag: (s: number) => void;
  onDragEnd: (s: number) => void;
  /** The browser took the gesture (pointercancel): drop the ghost. */
  onDragCancel?: () => void;
  /** ←/→ on the focused handle: -1 / +1, `big` = Shift held. */
  onStep?: (direction: -1 | 1, big: boolean) => void;
}

/** A faint reference line for the draggable mark — the moment it is
 * measured FROM (the music's own drop mark). */
export interface RulerDragRef {
  at_s: number;
  label: string;
}

const PAD_X = 16;
const RULER_W = 680;
const RULER_H = 108;
/** The handle lane under the ruler (only drawn with a dragMark). */
export const HANDLE_LANE_H = 44;
export const HANDLE_W = 104;
const HANDLE_H = 34;
/** Half-width of the line's own invisible grab strip, viewBox units. */
export const LINE_HIT_HALF_W = 9;

function tickStep(durationS: number): number {
  if (durationS <= 8) return 1;
  if (durationS <= 20) return 2;
  return 5;
}

const TONE: Record<string, string> = {
  accent: 'var(--accent)',
  muted: 'var(--text-muted)',
  hot: '#ff5a3c',
  predrop: PRE_DROP_COLOR,
};

export default function PreviewRuler({
  durationS, playheadS, bands, marks, triggerMarkS,
  onScrub, onTriggerDrag, onTriggerDragEnd, dragMark, dragRef,
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
  /** The one mark this preview lets him drag (the drop's red line). */
  dragMark?: RulerDragMark | null;
  dragRef?: RulerDragRef | null;
}) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const [focused, setFocused] = useState(false);
  const H = RULER_H + (dragMark ? HANDLE_LANE_H : 0);

  /** clientX -> viewBox x. The SVG keeps its aspect ratio (meet), so on a
   * wide card the 680-wide drawing is centred with margins either side and
   * on a narrow one it is scaled down — the screen CTM knows both; the
   * plain rect ratio is the fallback where there is none (jsdom). */
  const clientToViewX = (clientX: number): number => {
    const svg = svgRef.current;
    if (!svg) return 0;
    const ctm = typeof svg.getScreenCTM === 'function' ? svg.getScreenCTM() : null;
    if (ctm && typeof svg.createSVGPoint === 'function') {
      const pt = svg.createSVGPoint();
      pt.x = clientX;
      pt.y = 0;
      return pt.matrixTransform(ctm.inverse()).x;
    }
    const rect = svg.getBoundingClientRect();
    return rect.width > 0 ? ((clientX - rect.left) / rect.width) * RULER_W : 0;
  };
  const xToS = (clientX: number): number => {
    const frac = (clientToViewX(clientX) - PAD_X) / (RULER_W - 2 * PAD_X);
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

  /** Grab the drag mark: one pointer owns the gesture until it lifts. */
  const grabDragMark = (e: React.PointerEvent) => {
    if (!dragMark) return;
    if (e.pointerType === 'mouse' && e.button !== 0) return;
    e.preventDefault();
    e.stopPropagation();
    const target = e.currentTarget as Element;
    try { target.setPointerCapture(e.pointerId); } catch { /* best effort */ }
    const owner = e.pointerId;
    // the finger's distance from the line, kept for the whole gesture
    const grab = dragMark.at_s - xToS(e.clientX);
    const at = (clientX: number) => xToS(clientX) + grab;
    let last = dragMark.at_s;
    const move = (ev: PointerEvent) => {
      if (ev.pointerId !== owner) return;
      ev.preventDefault();
      last = at(ev.clientX);
      dragMark.onDrag(last);
    };
    const stop = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
      window.removeEventListener('pointercancel', cancel);
    };
    const up = (ev: PointerEvent) => {
      if (ev.pointerId !== owner) return;
      stop();
      dragMark.onDragEnd(at(ev.clientX));
    };
    const cancel = (ev: PointerEvent) => {
      if (ev.pointerId !== owner) return;
      stop();
      dragMark.onDragCancel?.();
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
    window.addEventListener('pointercancel', cancel);
    dragMark.onDrag(last);
  };

  const stepKey = (e: React.KeyboardEvent) => {
    if (!dragMark?.onStep) return;
    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
    e.preventDefault();
    dragMark.onStep(e.key === 'ArrowLeft' ? -1 : 1, e.shiftKey);
  };

  const ticks: number[] = [];
  for (let t = 0; t <= durationS + 1e-6; t += tickStep(durationS)) ticks.push(t);

  return (
    <svg ref={svgRef} viewBox={`0 0 ${RULER_W} ${H}`}
      style={{ width: '100%', height: H, touchAction: 'none', cursor: 'pointer',
               userSelect: 'none', WebkitUserSelect: 'none' }}
      onPointerDown={scrub}>
      <rect x={0} y={0} width={RULER_W} height={H} fill="var(--panel-bg, #1a1024)" />
      {bands.map((b, i) => (
        <g key={`b${i}`}>
          <rect x={sToX(b.from_s)} y={22}
            width={Math.max(1, sToX(b.to_s) - sToX(b.from_s))} height={RULER_H - 46}
            fill={TONE[b.tone ?? 'accent']} opacity={b.tone === 'muted' ? 0.1 : 0.18} />
          {/* Band labels sit just INSIDE the top of the band, not at its
              foot: the foot is where the draggable trigger mark writes its
              own label, and a crossfade band centred on the mark used to
              print "crossfade" straight through "trigger". A band too
              narrow for its own label is left unlabelled rather than
              printed over its neighbour — a 278ms hang beside a 400ms drop
              ramp is a real case, not a hypothetical. */}
          {b.label && sToX(b.to_s) - sToX(b.from_s) >= 7 * b.label.length && (
            <text x={(sToX(b.from_s) + sToX(b.to_s)) / 2} y={36} fontSize={9}
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
          <text x={sToX(m.at_s)} y={13} fontSize={9} fill={TONE[m.tone ?? 'accent']}
            textAnchor="middle">{m.label}</text>
        </g>
      ))}
      {dragRef && (
        <g pointerEvents="none" data-testid="drag-ref">
          <line x1={sToX(dragRef.at_s)} x2={sToX(dragRef.at_s)} y1={16} y2={H - 4}
            stroke={TONE.hot} strokeWidth={1} strokeDasharray="2,3" opacity={0.6} />
          {dragMark && Math.abs(sToX(dragRef.at_s) - sToX(dragMark.at_s)) > HANDLE_W / 2 + 22 && (
            <text x={sToX(dragRef.at_s)} y={H - 6} fontSize={9} fill={TONE.hot}
              opacity={0.75} textAnchor="middle">{dragRef.label}</text>
          )}
        </g>
      )}
      <line x1={sToX(playheadS)} x2={sToX(playheadS)} y1={0} y2={H}
        stroke="#fff" strokeWidth={1.5} opacity={0.9} pointerEvents="none" />
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
      {dragMark && (() => {
        const x = sToX(dragMark.at_s);
        const hot = dragMark.active || focused;
        const hx = Math.max(2, Math.min(RULER_W - HANDLE_W - 2, x - HANDLE_W / 2));
        const hy = RULER_H + (HANDLE_LANE_H - HANDLE_H) / 2;
        const bubbleW = Math.max(56, dragMark.readout.length * 7 + 14);
        const bx = Math.max(2, Math.min(RULER_W - bubbleW - 2, x - bubbleW / 2));
        return (
          <g data-testid="drag-mark">
            {/* the lane's floor line, so the handle reads as sitting in its own row */}
            <line x1={0} x2={RULER_W} y1={RULER_H + 0.5} y2={RULER_H + 0.5}
              stroke="var(--text-muted)" opacity={0.25} pointerEvents="none" />
            {hot && (
              <line x1={x} x2={x} y1={16} y2={H - 4} stroke={TONE.hot}
                strokeWidth={9} opacity={0.22} pointerEvents="none" />
            )}
            <line x1={x} x2={x} y1={16} y2={hy} stroke={TONE.hot}
              strokeWidth={hot ? 3.5 : 2.5} pointerEvents="none" />
            {/* the line's own grab strip — transparent, but painted, so it
                takes the press; narrow enough to leave its neighbours alone */}
            <rect data-testid="drag-mark-line" x={x - LINE_HIT_HALF_W} y={16}
              width={LINE_HIT_HALF_W * 2} height={RULER_H - 16} fill="transparent"
              style={{ cursor: 'ew-resize', touchAction: 'none' }}
              onPointerDown={grabDragMark}>
              <title>{dragMark.title}</title>
            </rect>
            {/* the HANDLE: its own lane, a finger-sized tab that names the mark
                (its label lives here, not in the crowded label row at the
                top, where a drop-led switch's own label sits on the same x) */}
            <g data-testid="drag-mark-handle" role="slider" tabIndex={0}
              aria-label={`${dragMark.label} timing`} aria-valuetext={dragMark.valueText}
              style={{ cursor: 'ew-resize', touchAction: 'none', outline: 'none' }}
              onPointerDown={grabDragMark} onKeyDown={stepKey}
              onFocus={() => setFocused(true)} onBlur={() => setFocused(false)}>
              <title>{dragMark.title}</title>
              <rect x={hx} y={hy} width={HANDLE_W} height={HANDLE_H} rx={8}
                fill={TONE.hot} opacity={hot ? 1 : 0.92}
                stroke={hot ? '#fff' : 'none'} strokeWidth={hot ? 1.5 : 0} />
              {/* grip ridges at both ends: "this slides" without a glyph a
                  font might not carry */}
              {[hx + 6, hx + 9, hx + HANDLE_W - 9, hx + HANDLE_W - 6].map((gx) => (
                <line key={gx} x1={gx} x2={gx} y1={hy + 10} y2={hy + HANDLE_H - 10}
                  stroke="#1a1024" strokeWidth={1.2} opacity={0.55} pointerEvents="none" />
              ))}
              <text x={hx + HANDLE_W / 2} y={hy + HANDLE_H / 2 + 4} fontSize={11}
                fontWeight={700} fill="#1a1024" textAnchor="middle" pointerEvents="none">
                {dragMark.label} {dragMark.readout}
              </text>
            </g>
            {dragMark.active && (
              <g pointerEvents="none" data-testid="drag-mark-bubble">
                <rect x={bx} y={18} width={bubbleW} height={20} rx={5}
                  fill="rgba(0,0,0,0.85)" stroke={TONE.hot} strokeWidth={1} />
                <text x={bx + bubbleW / 2} y={32} fontSize={11} fill="#fff"
                  fontWeight={700} textAnchor="middle">{dragMark.readout}</text>
              </g>
            )}
          </g>
        );
      })()}
    </svg>
  );
}
