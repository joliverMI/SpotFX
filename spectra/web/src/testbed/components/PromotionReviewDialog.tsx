/** Push-to-real — the ONE write the music-analysis test bed can make
 * (data/spotfx-music-analysis-plan/report.md, "Two decisions" #2,
 * Admiral-approved 2026-09-09). This dialog IS the review step: it is the
 * only component wired to usePromoteToReal, and it only ever calls that
 * mutation with confirmed: true, from its own explicit "Confirm & push"
 * button — never from the click that opened it. See
 * spectra/services/testbed_promote.py's module docstring for the server
 * side of this gate. */
import { useState } from 'react';
import { useScenes, useSpotColorSets, usePromoteToReal } from '../../queries';
import { RESPONSE_CLASSES } from '../../types';
import type { ResponseClass, TriggerAction, TriggerActionKind } from '../../types';

const KIND_LABEL: Record<TriggerActionKind, string> = {
  fire_scene: 'Fire Scene', fire_response: 'Fire Response',
  select_color_set: 'Select Colours', fire_scene_update: 'Fire Update',
};

function blankAction(kind: TriggerActionKind): TriggerAction {
  if (kind === 'fire_scene') return { kind, scene_id: null, intensity: 0.5, color_set_id: null };
  if (kind === 'fire_response') return { kind, event_class: 'flare', intensity: 0.5 };
  if (kind === 'fire_scene_update') return { kind, intensity: 0.5 };
  return { kind, set_id: '' };
}

export default function PromotionReviewDialog({
  uri, timestampMs, sourceEngine, sourceMarkKind, onClose,
}: {
  uri: string;
  timestampMs: number;
  sourceEngine: string;
  sourceMarkKind: string;
  onClose: () => void;
}) {
  const { data: scenes } = useScenes();
  const { data: colorSets } = useSpotColorSets();
  const promote = usePromoteToReal();

  const [action, setAction] = useState<TriggerAction>(blankAction('fire_response'));
  const [offsetMs, setOffsetMs] = useState(0);

  const setKind = (kind: TriggerActionKind) => setAction(blankAction(kind));

  const handleConfirm = () => {
    promote.mutate({
      uri, timestamp_ms: timestampMs, action,
      source_engine: sourceEngine, source_mark_kind: sourceMarkKind,
      trigger_offset_ms: offsetMs,
      confirmed: true,
    }, { onSuccess: onClose });
  };

  return (
    <div className="testbed-promote-dialog-backdrop" onClick={onClose}>
      <div className="testbed-promote-dialog" onClick={(e) => e.stopPropagation()}>
        <div className="card-title" style={{ marginBottom: 8 }}>
          Push suggestion to your real triggers?
        </div>
        <div className="testbed-promote-dialog-warn">
          This writes a real, fireable trigger into your live show
          (storage/spectra/triggers.json) at the moment you confirm below —
          it never happens silently.
        </div>
        <p style={{ fontSize: 13, color: 'var(--text-muted)' }}>
          Suggested by <strong>{sourceEngine}</strong> ({sourceMarkKind}) at{' '}
          <strong>{(timestampMs / 1000).toFixed(2)}s</strong>. Review and, if
          needed, adjust the action it will fire before confirming.
        </p>

        <div style={{ marginBottom: 8 }}>
          <label>Action kind</label>
          <select value={action.kind} onChange={(e) => setKind(e.target.value as TriggerActionKind)}>
            {(Object.keys(KIND_LABEL) as TriggerActionKind[]).map((k) => (
              <option key={k} value={k}>{KIND_LABEL[k]}</option>
            ))}
          </select>
        </div>

        {action.kind === 'fire_scene' && (
          <div style={{ marginBottom: 8 }}>
            <label>Scene (leave unset for automatic pick)</label>
            <select
              value={action.scene_id ?? ''}
              onChange={(e) => setAction({ ...action, scene_id: e.target.value || null })}
            >
              <option value="">— automatic —</option>
              {(scenes ?? []).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
            <label>Intensity: {action.intensity.toFixed(2)}</label>
            <input type="range" min={0} max={1} step={0.01} value={action.intensity}
              onChange={(e) => setAction({ ...action, intensity: Number(e.target.value) })} />
          </div>
        )}

        {action.kind === 'fire_response' && (
          <div style={{ marginBottom: 8 }}>
            <label>Response class</label>
            <select
              value={action.event_class}
              onChange={(e) => setAction({ ...action, event_class: e.target.value as ResponseClass })}
            >
              {RESPONSE_CLASSES.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
            <label>Intensity: {action.intensity.toFixed(2)}</label>
            <input type="range" min={0} max={1} step={0.01} value={action.intensity}
              onChange={(e) => setAction({ ...action, intensity: Number(e.target.value) })} />
          </div>
        )}

        {action.kind === 'select_color_set' && (
          <div style={{ marginBottom: 8 }}>
            <label>Colour set</label>
            <select value={action.set_id} onChange={(e) => setAction({ ...action, set_id: e.target.value })}>
              <option value="">— choose —</option>
              {(colorSets ?? []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </div>
        )}

        {action.kind === 'fire_scene_update' && (
          <div style={{ marginBottom: 8 }}>
            <label>Intensity: {action.intensity.toFixed(2)}</label>
            <input type="range" min={0} max={1} step={0.01} value={action.intensity}
              onChange={(e) => setAction({ ...action, intensity: Number(e.target.value) })} />
          </div>
        )}

        <div style={{ marginBottom: 12 }}>
          <label>Trigger offset (ms, negative = fire earlier)</label>
          <input type="number" value={offsetMs} min={-60000} max={60000}
            onChange={(e) => setOffsetMs(Number(e.target.value))} />
        </div>

        {promote.isError && (
          <p style={{ color: 'var(--danger)', fontSize: 12 }}>
            {(promote.error as Error).message}
          </p>
        )}

        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <button onClick={onClose} disabled={promote.isPending}>Cancel</button>
          <button className="primary" onClick={handleConfirm} disabled={promote.isPending}>
            {promote.isPending ? 'Pushing…' : 'Confirm & push to real triggers'}
          </button>
        </div>
      </div>
    </div>
  );
}
