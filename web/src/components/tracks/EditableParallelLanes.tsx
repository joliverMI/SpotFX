import type { MusicEvent } from '../../types/events';
import { useEditorStore } from '../../store/editorStore';
import { LabelsInput, NumberInput, TextInput } from '../forms/inputs';
import EditableActionContainer from './EditableActionContainer';
import PreviewButton from '../PreviewButton';
import { previewMorphLane } from '../../lib/preview';

/** morph_set / scene_update lanes: one weighted pick per lane, all fire in parallel.
 * scene_update pins its four named lanes (First/Rest/Shape/Color) — no add/delete/rename. */
export default function EditableParallelLanes({ event }: { event: MusicEvent }) {
  const mutate = useEditorStore((s) => s.mutate);
  const pinned = event.event_type !== 'morph_set';
  const lanes = event.morph_lanes;

  return (
    <div className="track">
      <div className="track-header">
        <span>⫴</span>
        <span>Parallel lanes — one pick per lane, all fire together</span>
      </div>
      {lanes.map((lane, i) => (
        <div key={i} className="action-card" style={{ padding: 10 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, flexWrap: 'wrap' }}>
            {pinned ? (
              <span style={{ fontWeight: 600, fontSize: 13 }}>{lane.name || `Lane ${i + 1}`}</span>
            ) : (
              <TextInput value={lane.name} placeholder={`Lane ${i + 1}`} width={160}
                onChange={(v) => mutate((d) => { d.morph_lanes[i].name = v; })} />
            )}
            <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13 }}>
              <span style={{ color: 'var(--text-muted)' }}>offset</span>
              <NumberInput value={lane.offset_ms} step={10} width={90}
                onChange={(v) => mutate((d) => { d.morph_lanes[i].offset_ms = v ?? 0; })} />
              <span style={{ color: 'var(--text-muted)' }}>ms</span>
            </label>
            <span className="chip">🎲 1 of {lane.alternatives.length}</span>
            <span style={{ flex: 1 }} />
            {!pinned && (
              <button title="Move lane up" disabled={i === 0} style={{ padding: '2px 7px', fontSize: 12 }}
                onClick={() => mutate((d) => {
                  const [l] = d.morph_lanes.splice(i, 1);
                  d.morph_lanes.splice(i - 1, 0, l);
                })}>↑</button>
            )}
            <PreviewButton title="Preview — pick one alternative and fire it now (offset ignored)"
              run={() => previewMorphLane(lane)} />
            {!pinned && (
              <button className="danger" title="Delete lane" style={{ padding: '2px 7px', fontSize: 12 }}
                onClick={() => mutate((d) => { d.morph_lanes.splice(i, 1); })}>✕</button>
            )}
          </div>
          <div style={{ marginBottom: 6 }}>
            <LabelsInput value={lane.labels} placeholder="lane filter labels (merge with trigger labels)"
              onChange={(v) => mutate((d) => { d.morph_lanes[i].labels = v; })} />
          </div>
          <div style={{ marginLeft: 12 }}>
            <EditableActionContainer
              containerPath={`morph_lanes.${i}.alternatives`}
              actions={lane.alternatives}
              emptyNote="No alternatives — the lane is skipped."
            />
          </div>
        </div>
      ))}
      {!lanes.length && <p className="empty-note">No lanes.</p>}
      {!pinned && (
        <button style={{ fontSize: 12 }}
          onClick={() => mutate((d) => {
            d.morph_lanes.push({ name: '', labels: [], alternatives: [], offset_ms: 0 });
          })}>
          + Add lane
        </button>
      )}
    </div>
  );
}
