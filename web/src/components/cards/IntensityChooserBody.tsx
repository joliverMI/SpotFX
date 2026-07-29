import { useRef } from 'react';
import type { Action, IntensityChooserAction, IntensityLane } from '../../types/events';
import { newIntensityLane } from '../../lib/defaults';
import { uuid } from '../../lib/uid';
import { useEditorStore } from '../../store/editorStore';
import { cloneForPaste, useClipboard, writeClip } from '../../store/clipboard';
import { LabelsInput, NumberInput, TextInput } from '../forms/inputs';
import { ParentScopeToggle } from '../forms/ScopePicker';
import EditableActionContainer from '../tracks/EditableActionContainer';
import { groupPathOf } from './groupPath';
import PreviewButton from '../PreviewButton';
import { previewIntensityLane } from '../../lib/preview';
import HelpLink from '../../help/HelpLink';

const clamp01 = (v: number) => Math.max(0, Math.min(1, v));
const round2 = (v: number) => Math.round(v * 100) / 100;

/** Keep lanes[1:] ascending by threshold (stable — equal thresholds keep
 * their order, matching the engine's "later lane wins" tie-break). */
const sortLanes = (g: IntensityChooserAction) => {
  const rest = g.lanes.slice(1).sort((a, b) => a.threshold - b.threshold);
  g.lanes.splice(1, rest.length, ...rest);
};

/** Expanded body of an intensity_chooser card: the firing trigger's intensity
 * (after the song/genre scaler) selects exactly one lane. Lane 1 is the
 * default; each further lane starts at its draggable threshold dot. */
export default function IntensityChooserBody({ uid, action }: { uid: string; action: IntensityChooserAction }) {
  const draft = useEditorStore((s) => s.draft);
  const updateAction = useEditorStore((s) => s.updateAction);
  const clip = useClipboard();
  const stripRef = useRef<HTMLDivElement>(null);
  if (!draft) return null;
  const groupPath = groupPathOf(draft, uid);
  if (!groupPath) return null;

  const set = (fn: (g: IntensityChooserAction) => void) =>
    updateAction(uid, (a) => { if (a.type === 'intensity_chooser') fn(a); });

  const addLane = () => set((g) => {
    const last = g.lanes.length > 1 ? g.lanes[g.lanes.length - 1].threshold : 0;
    g.lanes.push(newIntensityLane(round2(clamp01(last + (1 - last) / 2))));
    sortLanes(g);
  });

  // Delete = merge into the lane to its left: its actions join that lane.
  const removeLane = (j: number) => set((g) => {
    const [gone] = g.lanes.splice(j, 1);
    if (gone) g.lanes[Math.max(0, j - 1)].actions.push(...gone.actions);
  });

  const dragDot = (laneId: string) => (e: React.PointerEvent) => {
    const strip = stripRef.current;
    if (!strip) return;
    e.preventDefault();
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
    const rect = strip.getBoundingClientRect();
    const move = (ev: PointerEvent) => {
      const v = round2(clamp01((ev.clientX - rect.left) / rect.width));
      set((g) => {
        const lane = g.lanes.find((l) => l.id === laneId);
        if (lane && lane !== g.lanes[0]) { lane.threshold = Math.max(0.01, v); sortLanes(g); }
      });
    };
    const up = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  };

  const laneLabel = (j: number) => (j === 0 ? 'Default' : `Lane ${j}`);

  return (
    <div style={{ marginBottom: 10 }}>
      <p style={{ fontSize: 13, color: 'var(--text-muted)', marginBottom: 8 }}>
        The trigger’s intensity (0–1, after the song’s intensity scale) picks ONE lane:
        the highest dot at or below it. Left of the first dot is the Default lane.
        <HelpLink topic="intensity-chooser" />
      </p>

      {/* Threshold strip with draggable dots */}
      <div ref={stripRef} style={{ position: 'relative', height: 34, margin: '4px 6px 14px' }}>
        <div style={{
          position: 'absolute', inset: '12px 0', borderRadius: 6,
          background: 'linear-gradient(90deg, color-mix(in srgb, var(--accent) 12%, transparent), color-mix(in srgb, var(--accent) 55%, transparent))',
          border: '1px solid var(--border)',
        }} />
        {/* region labels */}
        {action.lanes.map((lane, j) => {
          const start = j === 0 ? 0 : lane.threshold;
          const end = j + 1 < action.lanes.length ? action.lanes[j + 1].threshold : 1;
          if (end - start < 0.06) return null;
          return (
            <span key={`r${lane.id}`} style={{
              position: 'absolute', top: 12, height: 22, lineHeight: '22px',
              left: `${((start + end) / 2) * 100}%`, transform: 'translateX(-50%)',
              fontSize: 10, color: 'var(--text-muted)', pointerEvents: 'none', whiteSpace: 'nowrap',
            }}>{j === 0 ? 'default' : j}</span>
          );
        })}
        {/* draggable dots for lanes 1..N */}
        {action.lanes.slice(1).map((lane, k) => (
          <div key={lane.id} onPointerDown={dragDot(lane.id)}
            title={`Lane ${k + 1} starts at ${lane.threshold.toFixed(2)} — drag to move`}
            style={{
              position: 'absolute', top: 3, left: `${lane.threshold * 100}%`,
              transform: 'translateX(-50%)', width: 20, height: 20, borderRadius: '50%',
              background: 'var(--accent)', color: 'var(--bg, #fff)', cursor: 'ew-resize',
              fontSize: 11, fontWeight: 700, display: 'flex', alignItems: 'center',
              justifyContent: 'center', userSelect: 'none', touchAction: 'none',
              boxShadow: '0 1px 3px rgba(0,0,0,0.4)', zIndex: 2,
            }}>{k + 1}</div>
        ))}
      </div>

      {action.lanes.map((lane, j) => (
        <div key={lane.id} className="action-card" style={{ padding: 10, marginBottom: 8 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, flexWrap: 'wrap' }}>
            <TextInput value={lane.name} placeholder={laneLabel(j)} width={150}
              onChange={(v) => set((g) => { const l = g.lanes.find((x) => x.id === lane.id); if (l) l.name = v; })} />
            {j === 0 ? (
              <span style={{ fontSize: 12, color: 'var(--text-muted)' }}
                title="Fires when intensity is below every dot, or when the fire has no intensity (manual tests)">
                below first dot / no intensity
              </span>
            ) : (
              <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13 }}
                title="Lower bound: this lane covers intensities from here up to the next dot">
                <span style={{ color: 'var(--text-muted)' }}>from</span>
                <NumberInput value={lane.threshold} min={0.01} max={1} step={0.05} width={70}
                  onChange={(v) => set((g) => {
                    const l = g.lanes.find((x) => x.id === lane.id);
                    if (l) { l.threshold = clamp01(v ?? 0.5); sortLanes(g); }
                  })} />
              </label>
            )}
            <span style={{ flex: 1 }} />
            <button title="Copy lane" style={{ padding: '2px 7px', fontSize: 12 }}
              onClick={() => writeClip('intensity_lane', lane, `lane “${lane.name || laneLabel(j)}” · ${lane.actions.length} actions`)}>📋</button>
            <button title="Duplicate lane" style={{ padding: '2px 7px', fontSize: 12 }}
              onClick={() => set((g) => {
                const clone = JSON.parse(JSON.stringify(lane, (k, v) => (k.startsWith('_') ? undefined : v))) as IntensityLane;
                clone.id = uuid();
                clone.threshold = round2(clamp01(lane.threshold + 0.05));
                g.lanes.push(clone);
                sortLanes(g);
              })}>⧉</button>
            <PreviewButton title="Preview — fire this lane now (threshold ignored)"
              run={() => previewIntensityLane(action, lane)} />
            <button className="danger" disabled={action.lanes.length === 1}
              title={j === 0 ? 'Delete default lane (the next lane becomes the default)' : 'Delete lane (its actions merge into the lane to its left)'}
              style={{ padding: '2px 7px', fontSize: 12 }}
              onClick={() => removeLane(j)}>✕</button>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6, flexWrap: 'wrap' }}>
            <span style={{ fontSize: 12, color: 'var(--text-muted)' }} title="Device/category this lane targets (empty leaf scopes adopt it)">target</span>
            <ParentScopeToggle scope={lane.scope} onChange={(s) => set((g) => { const l = g.lanes.find((x) => x.id === lane.id); if (l) l.scope = s; })} />
          </div>
          <div style={{ marginBottom: 6 }}>
            <LabelsInput value={lane.labels} placeholder="lane filter labels (merge with trigger labels)"
              onChange={(v) => set((g) => { const l = g.lanes.find((x) => x.id === lane.id); if (l) l.labels = v; })} />
          </div>
          <div style={{ marginLeft: 12 }}>
            <EditableActionContainer
              containerPath={`${groupPath}.lanes.${j}.actions`}
              actions={lane.actions}
              emptyNote="No actions — this lane fires nothing."
            />
          </div>
        </div>
      ))}
      <button style={{ fontSize: 12 }} onClick={addLane}>+ Add lane</button>
      {(clip?.kind === 'intensity_lane' || clip?.kind === 'action') && (
        <button style={{ fontSize: 12, marginLeft: 6 }} title={`Paste “${clip.summary}”`}
          onClick={() => set((g) => {
            if (clip.kind === 'intensity_lane') {
              g.lanes.push(cloneForPaste(clip.data as IntensityLane));
            } else {
              const l = newIntensityLane(g.lanes.length > 1 ? round2(clamp01(g.lanes[g.lanes.length - 1].threshold + 0.05)) : 0.5);
              l.actions.push(cloneForPaste(clip.data as Action));
              g.lanes.push(l);
            }
            sortLanes(g);
          })}>
          📋 Paste lane
        </button>
      )}
    </div>
  );
}
