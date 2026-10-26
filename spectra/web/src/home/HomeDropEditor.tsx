/** A DROP'S EDITOR, IN PLACE (the Home Drops panel's pencil — predrop plan
 * step 1, report section 3.6: "the pencil opens the drop in place: a zoomed
 * strip of the audio shape from the charge to two beats after the drop,
 * with ... large handles ... that drag with the Timeline's own snapping").
 *
 * Touch and mouse alike: each handle is a 44 px button (`touch-action:
 * none`, AGENTS.md's hold/drag rule) that drags with the Timeline's own
 * snapping (../timeline/dropEdit.ts: the bass spikes and beats the detector
 * counts), steps along those rails with its ◀ ▶ buttons or the arrow keys,
 * and never crosses its neighbour (charge < lull < drop, RAMP_FLOOR_MS
 * apart). ONE SAVE ON RELEASE, one undo step per edit — the Timeline's own
 * contract (useDropEditor). A drop of HIS OWN moves his trigger in his song
 * profile (the same `/handles` route; spectra/services/drop_panel.py). The
 * window is fixed while he drags, so the strip never slides under his
 * finger. */
import { useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import Icon from '../components/Icon';
import type { DropEditor } from '../timeline/hooks/useDropEditor';
import { useAudioShapeData, useDropRails } from '../timeline/queries';
import type { Handle } from '../timeline/dropSequences';
import { HANDLES } from '../timeline/dropSequences';
import {
  changedHandles, clampHandle, snapHandle, snapRadiusMs, stepHandle, type HandleTimes,
} from '../timeline/dropEdit';
import { fmtDropTime, PART_COLOR, PART_LABEL, type PanelRow } from './dropsPanel';

const STRIP_H = 96;

export default function HomeDropEditor({ row, uri, beatMs, editor, onClose }: {
  row: PanelRow;
  uri: string;
  beatMs: number;
  editor: DropEditor;
  onClose: () => void;
}) {
  const { data: rails } = useDropRails(uri);
  const { data: shape } = useAudioShapeData(uri, true);
  const saved: HandleTimes = useMemo(
    () => ({ charge: row.chargeMs, lull: row.lullMs, drop: row.dropMs }),
    [row.chargeMs, row.lullMs, row.dropMs]);
  const [ghost, setGhost] = useState<HandleTimes | null>(null);
  const [guide, setGuide] = useState<string | null>(null);
  const times = ghost ?? saved;

  // THE WINDOW: two beats before the first handle to two after the drop,
  // from the SAVED times — a drag never moves it.
  const beat = beatMs > 0 ? beatMs : 500;
  const startMs = Math.max(0, (saved.charge ?? saved.lull ?? saved.drop!) - 2 * beat);
  const endMs = (saved.drop ?? 0) + 2 * beat;
  const span = Math.max(1, endMs - startMs);
  const pct = (ms: number) => ((ms - startMs) / span) * 100;

  // a saved move lands in the cached view, which hands this a new row: the
  // ghost has done its job once the drawn view caught up
  useEffect(() => { setGhost(null); }, [saved]);

  const stripRef = useRef<HTMLDivElement>(null);
  const shapePath = useMemo(() => {
    if (!shape?.timestamps_ms?.length) return null;
    const ts = shape.timestamps_ms;
    const vals = shape.rms_total;
    let peak = 1e-9;
    const pts: [number, number][] = [];
    for (let i = 0; i < ts.length; i++) {
      if (ts[i] < startMs || ts[i] > endMs) continue;
      pts.push([ts[i], vals[i]]);
      if (vals[i] > peak) peak = vals[i];
    }
    if (pts.length < 2) return null;
    const x = (ms: number) => (((ms - startMs) / span) * 1000).toFixed(1);
    const y = (v: number) => (STRIP_H - (v / peak) * (STRIP_H - 10)).toFixed(1);
    return `M${x(pts[0][0])} ${STRIP_H} ` + pts.map(([t, v]) => `L${x(t)} ${y(v)}`).join(' ')
      + ` L${x(pts[pts.length - 1][0])} ${STRIP_H} Z`;
  }, [shape, startMs, endMs, span]);

  const msAt = (clientX: number): number => {
    const r = stripRef.current?.getBoundingClientRect();
    if (!r || r.width <= 0) return times.drop ?? startMs;
    return startMs + ((clientX - r.left) / r.width) * span;
  };

  const save = async (next: HandleTimes, what: string) => {
    const changed = changedHandles(saved, next);
    if (Object.keys(changed).length === 0) {
      setGhost(null);
      return;
    }
    const ok = await editor.moveHandles(row.key, changed, what);
    // a refused move keeps the saved place; the error is the editor's to show
    if (ok == null) setGhost(null);
  };

  const drag = (h: Handle) => (ev: React.PointerEvent<HTMLButtonElement>) => {
    ev.preventDefault();
    const btn = ev.currentTarget;
    btn.setPointerCapture(ev.pointerId);
    const width = stripRef.current?.getBoundingClientRect().width ?? 300;
    const radius = snapRadiusMs(width, startMs, endMs);
    // this drag's own latest place — never a ref one render behind it
    let last: HandleTimes | null = null;
    const move = (e: PointerEvent) => {
      if (e.pointerId !== ev.pointerId) return;
      const g = snapHandle(h, msAt(e.clientX), rails ?? null, radius, e.altKey);
      const base = last ?? saved;
      const at = clampHandle(base, h, g.ms);
      last = { ...base, [h]: at };
      setGhost(last);
      setGuide(`${PART_LABEL[h]} → ${fmtDropTime(at)} (${g.what})`);
    };
    const up = (e: PointerEvent) => {
      if (e.pointerId !== ev.pointerId) return;
      try { btn.releasePointerCapture(e.pointerId); } catch { /* already gone */ }
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
      window.removeEventListener('pointercancel', up);
      setGuide(null);
      if (last && e.type === 'pointerup') void save(last, `moved the ${h}`);
      else setGhost(null);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
    window.addEventListener('pointercancel', up);
  };

  const step = (h: Handle, dir: 1 | -1, nudge = false) => {
    const at = times[h];
    if (at == null) return;
    const g = stepHandle(h, at, dir, rails ?? null, nudge);
    if (!g) return;
    const next = { ...times, [h]: clampHandle(times, h, g.ms) };
    void save(next, `stepped the ${h} ${dir > 0 ? 'later' : 'earlier'}`);
  };

  const present = HANDLES.filter((h) => times[h] != null);
  const moved = row.view?.moved ?? {};
  const anyMoved = HANDLES.some((h) => moved[h]);

  return (
    <div className="home-drop-editor" role="group"
      aria-label={`Edit the drop at ${fmtDropTime(row.dropMs)}`}>
      <div className="home-drop-editor-strip" ref={stripRef} style={{ height: STRIP_H }}>
        <svg viewBox={`0 0 1000 ${STRIP_H}`} preserveAspectRatio="none" aria-hidden
          className="home-drop-editor-svg">
          {shapePath && <path d={shapePath} className="home-drop-editor-shape" />}
          {(rails?.beats ?? []).filter(([ms]) => ms >= startMs && ms <= endMs).map(([ms, down]) => (
            <line key={`b${ms}`} x1={pct(ms) * 10} x2={pct(ms) * 10} y1={down ? 0 : STRIP_H * 0.55}
              y2={STRIP_H} className={down ? 'home-drop-editor-downbeat' : 'home-drop-editor-beat'} />
          ))}
          {(rails?.spikes ?? []).filter(([ms]) => ms >= startMs && ms <= endMs).map(([ms, rise]) => (
            <line key={`s${ms}`} x1={pct(ms) * 10} x2={pct(ms) * 10}
              y1={STRIP_H - Math.min(1, rise) * (STRIP_H - 12)} y2={STRIP_H}
              className="home-drop-editor-spike" />
          ))}
          {present.map((h) => (
            <line key={`h${h}`} x1={pct(times[h]!) * 10} x2={pct(times[h]!) * 10} y1={0}
              y2={STRIP_H} stroke={PART_COLOR[h]} strokeWidth={3} vectorEffect="non-scaling-stroke" />
          ))}
        </svg>
        {present.map((h) => (
          <button key={h} type="button" className={`home-drop-editor-handle ${h}`}
            style={{ left: `${pct(times[h]!)}%`, ['--part' as string]: PART_COLOR[h] }}
            aria-label={`${PART_LABEL[h]} at ${fmtDropTime(times[h]!)} — drag, or use the arrow keys`}
            title={`${PART_LABEL[h]} ${fmtDropTime(times[h]!)} — drag to move (it snaps to the bass spikes and beats)`}
            onPointerDown={drag(h)}
            onKeyDown={(e) => {
              if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
                e.preventDefault();
                step(h, e.key === 'ArrowRight' ? 1 : -1, e.shiftKey);
              }
            }}>
            <span aria-hidden className="home-drop-editor-grip" />
          </button>
        ))}
      </div>
      <div className="home-drop-editor-guide" aria-live="polite">
        {guide ?? `${fmtDropTime(startMs)} – ${fmtDropTime(endMs)} · drag a handle; it snaps to a bass spike or a beat`}
      </div>
      <div className="home-drop-editor-steps">
        {present.map((h) => (
          <span key={h} className="home-drop-editor-step" style={{ ['--part' as string]: PART_COLOR[h] }}>
            <button type="button" className="home-drop-editor-stepbtn"
              aria-label={`${PART_LABEL[h]} earlier`} title={`${PART_LABEL[h]}: back to the previous spike or beat`}
              onClick={() => step(h, -1)}>◀</button>
            <b>{PART_LABEL[h]}</b>
            <button type="button" className="home-drop-editor-stepbtn"
              aria-label={`${PART_LABEL[h]} later`} title={`${PART_LABEL[h]}: on to the next spike or beat`}
              onClick={() => step(h, 1)}>▶</button>
          </span>
        ))}
      </div>
      <div className="home-drop-editor-actions">
        {row.kind === 'detected' && (
          <button type="button" className="home-drop-editor-act" disabled={!anyMoved}
            title="Back to where the analysis puts it (forgets your moves on this drop)"
            onClick={() => void editor.revert(row.key, fmtDropTime(row.dropMs))}>
            Back to detected
          </button>
        )}
        <button type="button" className="home-drop-editor-act" disabled={!editor.canUndo}
          title={editor.undoLabel ? `Undo: ${editor.undoLabel}` : 'Nothing to undo'}
          onClick={() => void editor.undo()}>
          <Icon name="undo" size={14} /> Undo
        </button>
        <Link to="/timeline" className="home-drop-editor-act">
          <Icon name="open" size={14} /> Open the Timeline
        </Link>
        <button type="button" className="home-drop-editor-act" onClick={onClose}>Done</button>
      </div>
    </div>
  );
}
