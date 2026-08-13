import { useState } from 'react';
import { SCENE_LANE_NAMES, type MusicEvent } from '../../types/events';
import { useEditorStore } from '../../store/editorStore';
import { LabelsInput, NumberInput, TextInput } from '../forms/inputs';
import EditableActionContainer from './EditableActionContainer';
import PreviewButton from '../PreviewButton';
import { previewMorphLane } from '../../lib/preview';
import { apiPost } from '../../api/client';

/** Fire the real Charge → Lull → Drop arc (backend spaces the three fixed
 * events by the configured phase ramps). Runs against the ACTIVE scene's
 * phase lanes — fire the scene first if you want THIS scene's lanes. */
export function PhaseCycleButton() {
  const [busy, setBusy] = useState(false);
  return (
    <button style={{ fontSize: 12 }} disabled={busy}
      title="Fire Charge, then Lull, then Drop, spaced by the configured phase ramps. Acts on live phase-capable effects + the ACTIVE scene's Charge/Lull/Drop lanes — fire this scene first to make it the active one."
      onClick={async () => {
        setBusy(true);
        try {
          const r = await apiPost<{ charge_ramp_ms: number; lull_ramp_ms: number; drop_ramp_ms: number }>(
            '/events/phase-cycle/fire');
          const total = r.charge_ramp_ms + 400 + r.lull_ramp_ms + 900 + r.drop_ramp_ms + 1500;
          setTimeout(() => setBusy(false), total);
        } catch {
          setBusy(false);
        }
      }}>
      {busy ? '⏳ cycling…' : '▶ Charge → Lull → Drop cycle'}
    </button>
  );
}

/** morph_set / scene_update lanes: one weighted pick per lane, all fire in parallel.
 * scene_update pins its named lanes (First/Rest/Shape/Color/Charge/Lull/Drop) —
 * no add/delete/rename. Older scenes carry only the first four; a one-click
 * button appends the Charge/Lull/Drop lanes. */
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
              <span style={{ fontWeight: 600, fontSize: 13 }}>{lane.name || SCENE_LANE_NAMES[i] || `Lane ${i + 1}`}</span>
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
      {pinned && event.event_type === 'scene_update' && (
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {lanes.length < SCENE_LANE_NAMES.length && (
            <button style={{ fontSize: 12 }}
              title="Charge/Lull/Drop lanes carry extra per-scene param tweaks fired alongside the effect phase choreography"
              onClick={() => mutate((d) => {
                while (d.morph_lanes.length < SCENE_LANE_NAMES.length) {
                  d.morph_lanes.push({
                    name: SCENE_LANE_NAMES[d.morph_lanes.length],
                    labels: [], alternatives: [], offset_ms: 0,
                  });
                }
              })}>
              + Add Charge / Lull / Drop lanes
            </button>
          )}
          <PhaseCycleButton />
        </div>
      )}
    </div>
  );
}
