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
 * finger.
 *
 * THE PRE-DROP (predrop plan step 4) is the fourth handle: orange, wearing
 * its kind's glyph, hanging over the strip's TOP edge so it never sits on
 * the drop's own handle below. It snaps to the rail of its kind — a spike
 * to the hits, a vocal intro to the entries (./dropsPanel.ts `snapPreDrop`)
 * — and stays inside its kind's lead range before the drop. One tap on the
 * glyph beside its ◀ ▶ switches its kind; ＋ Pre-drop places one where the
 * rules pick when the drop has none. On his own drop it moves the same way
 * (the server keeps it in the drop store, never his song profile). Nothing
 * plays from a pre-drop yet. */
import { useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import Icon from '../components/Icon';
import type { DropEditor } from '../timeline/hooks/useDropEditor';
import { useAudioShapeData, useDropRails } from '../timeline/queries';
import type { Handle, PreDropKind } from '../timeline/dropSequences';
import { HANDLES } from '../timeline/dropSequences';
import {
  changedHandles, clampHandle, snapHandle, snapRadiusMs, stepHandle, type HandleTimes,
} from '../timeline/dropEdit';
import {
  clampPreDrop, fmtDropTime, PART_COLOR, PART_LABEL, PRE_DROP_KIND_WORD, PRE_DROP_LEAD_MS,
  PRE_DROPS_DO_NOT_PLAY, preDropRail, snapPreDrop, stepPreDrop, type PanelRow,
} from './dropsPanel';

const STRIP_H = 96;

const KIND_ICON = { spike: 'preDrop', intro: 'preDropVoice' } as const;
const OTHER_KIND: Record<PreDropKind, PreDropKind> = { spike: 'intro', intro: 'spike' };

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
  const [preGhost, setPreGhost] = useState<number | null>(null);
  const [guide, setGuide] = useState<string | null>(null);
  const times = ghost ?? saved;
  const preKind = row.preDropKind;
  const savedPre = row.preDropMs;
  const preAt = preGhost ?? savedPre;

  // THE WINDOW: two beats before the first handle to two after the drop,
  // from the SAVED times — a drag never moves it.
  const beat = beatMs > 0 ? beatMs : 500;
  const firstMs = Math.min(...[saved.charge, saved.lull, savedPre, row.preDropWas, saved.drop]
    .filter((v): v is number => v != null));
  const startMs = Math.max(0, firstMs - 2 * beat);
  const endMs = (saved.drop ?? 0) + 2 * beat;
  const span = Math.max(1, endMs - startMs);
  const pct = (ms: number) => ((ms - startMs) / span) * 100;

  // a saved move lands in the cached view, which hands this a new row: the
  // ghost has done its job once the drawn view caught up
  useEffect(() => { setGhost(null); }, [saved]);
  useEffect(() => { setPreGhost(null); }, [savedPre, preKind]);

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

  const savePre = async (next: number, what: string) => {
    if (next === savedPre) {
      setPreGhost(null);
      return;
    }
    setPreGhost(next);
    const ok = await editor.moveHandles(row.key, { pre_drop: next }, what);
    if (ok == null) setPreGhost(null);
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

  /** The pre-drop's drag: its kind's rail, inside its lead range. */
  const dragPre = (ev: React.PointerEvent<HTMLButtonElement>) => {
    if (!preKind) return;
    ev.preventDefault();
    const btn = ev.currentTarget;
    btn.setPointerCapture(ev.pointerId);
    const width = stripRef.current?.getBoundingClientRect().width ?? 300;
    const radius = snapRadiusMs(width, startMs, endMs);
    let last: number | null = null;
    const move = (e: PointerEvent) => {
      if (e.pointerId !== ev.pointerId) return;
      const g = snapPreDrop(preKind, msAt(e.clientX), rails, radius, e.altKey);
      last = clampPreDrop(preKind, row.dropMs, g.ms);
      setPreGhost(last);
      setGuide(`Pre-drop → ${fmtDropTime(last)}, ${row.dropMs - last} ms before the drop (${g.what})`);
    };
    const up = (e: PointerEvent) => {
      if (e.pointerId !== ev.pointerId) return;
      try { btn.releasePointerCapture(e.pointerId); } catch { /* already gone */ }
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
      window.removeEventListener('pointercancel', up);
      setGuide(null);
      if (last != null && e.type === 'pointerup') void savePre(last, 'moved the pre-drop');
      else setPreGhost(null);
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

  const stepPre = (dir: 1 | -1, nudge = false) => {
    if (preAt == null || !preKind) return;
    const g = stepPreDrop(preKind, preAt, dir, rails, nudge);
    if (!g) return;
    void savePre(clampPreDrop(preKind, row.dropMs, g.ms),
      `stepped the pre-drop ${dir > 0 ? 'later' : 'earlier'}`);
  };

  const present = HANDLES.filter((h) => times[h] != null);
  const moved = row.view?.moved ?? {};
  const anyMoved = HANDLES.some((h) => moved[h]) || !!moved.pre_drop;
  const hasPre = preAt != null && !!preKind;
  const preAbsent = row.parts.pre_drop === 'absent';
  const preColor = PART_COLOR.pre_drop;
  const railTicks = preKind
    ? preDropRail(preKind, rails).filter(([ms]) => ms >= startMs && ms <= endMs) : [];
  const preWord = preKind ? PRE_DROP_KIND_WORD[preKind] : '';
  // a kind switch keeps the pre-drop where it is, so it is refused (the
  // server's own rule) when its lead does not fit the other kind's range —
  // say so on the button rather than send a switch that cannot land
  const otherKind = preKind ? OTHER_KIND[preKind] : null;
  const preLead = hasPre ? row.dropMs - preAt! : null;
  const otherRange = otherKind ? PRE_DROP_LEAD_MS[otherKind] : null;
  const kindFits = otherRange != null && preLead != null
    && preLead >= otherRange[0] && preLead <= otherRange[1];
  const kindTitle = !otherKind ? ''
    : kindFits ? `Pre-drop: ${preWord} — tap to make it ${PRE_DROP_KIND_WORD[otherKind]}`
      : `Pre-drop: ${preWord} — ${PRE_DROP_KIND_WORD[otherKind]} sits ${otherRange![0]}–${otherRange![1]} ms `
        + `before its drop and this one is ${preLead} ms; move it first`;

  return (
    <div className="home-drop-editor" role="group"
      aria-label={`Edit the drop at ${fmtDropTime(row.dropMs)}`}>
      <div className={`home-drop-editor-strip${hasPre ? ' has-pre' : ''}`} ref={stripRef}
        style={{ height: STRIP_H }}>
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
          {/* the rail the pre-drop snaps to (its kind's), from the top edge */}
          {railTicks.map(([ms, strength]) => (
            <line key={`p${ms}`} x1={pct(ms) * 10} x2={pct(ms) * 10} y1={0}
              y2={Math.max(6, Math.min(1, strength) * STRIP_H * 0.5)}
              className={`home-drop-editor-prerail ${preKind}`} />
          ))}
          {present.map((h) => (
            <line key={`h${h}`} x1={pct(times[h]!) * 10} x2={pct(times[h]!) * 10} y1={0}
              y2={STRIP_H} stroke={PART_COLOR[h]} strokeWidth={3} vectorEffect="non-scaling-stroke" />
          ))}
          {hasPre && (
            <line x1={pct(preAt!) * 10} x2={pct(preAt!) * 10} y1={0} y2={STRIP_H}
              stroke={preColor} strokeWidth={3} vectorEffect="non-scaling-stroke" />
          )}
          {!hasPre && row.preDropWas != null && (
            <line x1={pct(row.preDropWas) * 10} x2={pct(row.preDropWas) * 10} y1={0} y2={STRIP_H}
              stroke={preColor} strokeWidth={2} strokeDasharray="4 4" opacity={0.5}
              vectorEffect="non-scaling-stroke" className="home-drop-editor-preoff" />
          )}
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
        {hasPre && (
          <button type="button" className="home-drop-editor-handle pre_drop"
            data-kind={preKind}
            style={{ left: `${pct(preAt!)}%`, ['--part' as string]: preColor }}
            aria-label={`Pre-drop (${preWord}) at ${fmtDropTime(preAt!)}, ${row.dropMs - preAt!} ms before the drop — drag, or use the arrow keys`}
            title={`Pre-drop (${preWord}) ${fmtDropTime(preAt!)} — drag to move (it snaps to ${preKind === 'intro' ? 'the vocal entries' : 'the hits'}); ${PRE_DROPS_DO_NOT_PLAY}`}
            onPointerDown={dragPre}
            onKeyDown={(e) => {
              if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
                e.preventDefault();
                stepPre(e.key === 'ArrowRight' ? 1 : -1, e.shiftKey);
              }
            }}>
            <span aria-hidden className="home-drop-editor-grip">
              <Icon name={KIND_ICON[preKind!]} size={13} />
            </span>
          </button>
        )}
      </div>
      <div className="home-drop-editor-guide" aria-live="polite">
        {guide ?? (row.preDropWas != null && !hasPre
          ? 'The pre-drop is off — tap its button in the row to switch it back on'
          : `${fmtDropTime(startMs)} – ${fmtDropTime(endMs)} · drag a handle; it snaps to a bass spike or a beat${hasPre ? `, the pre-drop to ${preKind === 'intro' ? 'a vocal entry' : 'a hit'}` : ''}`)}
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
        {hasPre && (
          <span className="home-drop-editor-step pre_drop" style={{ ['--part' as string]: preColor }}>
            <button type="button" className="home-drop-editor-stepbtn pre-earlier"
              aria-label="Pre-drop earlier"
              title={`Pre-drop: back to the previous ${preKind === 'intro' ? 'vocal entry' : 'hit'}`}
              onClick={() => stepPre(-1)}>◀</button>
            <button type="button" className="home-drop-editor-kind" data-kind={preKind}
              disabled={!kindFits} aria-label={kindTitle} title={kindTitle}
              onClick={() => void editor.preDropKind(row.key, otherKind!)}>
              <Icon name={KIND_ICON[preKind!]} size={16} />
            </button>
            <b>{PART_LABEL.pre_drop}</b>
            <button type="button" className="home-drop-editor-stepbtn pre-later"
              aria-label="Pre-drop later"
              title={`Pre-drop: on to the next ${preKind === 'intro' ? 'vocal entry' : 'hit'}`}
              onClick={() => stepPre(1)}>▶</button>
          </span>
        )}
      </div>
      <div className="home-drop-editor-actions">
        {preAbsent && savedPre == null && row.preDropWas == null && (
          <button type="button" className="home-drop-editor-act add-pre-drop"
            title={`Add a pre-drop where the rules find the strongest hit or vocal entry before this drop; ${PRE_DROPS_DO_NOT_PLAY}`}
            onClick={() => void editor.fill(row.key, 'pre_drop')}>
            <Icon name="preDrop" size={14} /> ＋ Pre-drop
          </button>
        )}
        {row.preDropMoved && row.preDropAuto != null && hasPre && (
          <button type="button" className="home-drop-editor-act pre-back"
            title={row.kind === 'yours'
              ? 'Pre-drop back to where the rules put it before your drop'
              : 'Pre-drop back to where the analysis puts it (the other handles stay)'}
            onClick={() => void editor.moveHandles(row.key, { pre_drop: null },
              'pre-drop back to detected')}>
            Pre-drop back to detected
          </button>
        )}
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
