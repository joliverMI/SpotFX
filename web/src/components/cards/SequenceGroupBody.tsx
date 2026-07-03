import type { GroupRevert, SequenceChild, SequenceGroupAction } from '../../types/events';
import { newSequenceChild } from '../../lib/defaults';
import { uuid } from '../../lib/uid';
import { useEditorStore } from '../../store/editorStore';
import { Checkbox, LabelsInput, NumberInput, Select } from '../forms/inputs';
import EditableActionContainer from '../tracks/EditableActionContainer';
import { groupPathOf } from './groupPath';

const defaultRevert = (): GroupRevert => ({
  enabled: true, delay_ms: 0, delay_beats: 0, transition_ms: 500, pre_ramp: true,
});

/** Expanded body of a sequence_group card: ordered children with ms/beat
 * delays, each holding a nested droppable action list. */
export default function SequenceGroupBody({ uid, action }: { uid: string; action: SequenceGroupAction }) {
  const draft = useEditorStore((s) => s.draft);
  const updateAction = useEditorStore((s) => s.updateAction);
  if (!draft) return null;
  const groupPath = groupPathOf(draft, uid);
  if (!groupPath) return null;

  const set = (fn: (g: SequenceGroupAction) => void) =>
    updateAction(uid, (a) => { if (a.type === 'sequence_group') fn(a); });
  const beats = action.timing === 'beats';
  const revert = action.revert;

  return (
    <div style={{ marginBottom: 10 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 8, flexWrap: 'wrap' }}>
        <span style={{ fontSize: 13, color: 'var(--text-muted)' }}>Children fire in order.</span>
        <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13 }}>
          <span style={{ color: 'var(--text-muted)' }}>timing</span>
          <Select value={action.timing} width={100}
            onChange={(v) => set((g) => { g.timing = v as 'ms' | 'beats'; })}
            options={[{ value: 'ms', label: 'ms' }, { value: 'beats', label: 'beats' }]} />
        </label>
        {beats && (
          <>
            <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13 }}>
              <span style={{ color: 'var(--text-muted)' }} title="When the song has no beat data">no beats</span>
              <Select value={action.beat_fallback} width={110}
                onChange={(v) => set((g) => { g.beat_fallback = v as 'skip' | 'fallback'; })}
                options={[{ value: 'fallback', label: 'fallback' }, { value: 'skip', label: 'skip' }]} />
            </label>
            <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13 }}>
              <span style={{ color: 'var(--text-muted)' }}>start offset</span>
              <NumberInput value={action.start_offset_beats} step={1} width={70}
                onChange={(v) => set((g) => { g.start_offset_beats = Math.round(v ?? 0); })} />
              <span style={{ color: 'var(--text-muted)' }}>beats</span>
            </label>
          </>
        )}
      </div>

      {action.children.map((child, j) => (
        <div key={child.id} className="action-card" style={{ padding: 10, marginBottom: 8 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, flexWrap: 'wrap' }}>
            <span className="step-badge">{j + 1}</span>
            <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13 }}>
              <span style={{ color: 'var(--text-muted)' }}>{beats ? '+beats' : 'delay'}</span>
              {beats ? (
                <NumberInput value={child.delay_beats} min={0} step={1} width={70}
                  onChange={(v) => set((g) => { g.children[j].delay_beats = Math.max(0, Math.round(v ?? 0)); })} />
              ) : (
                <NumberInput value={child.delay_ms} min={0} step={50} width={90}
                  onChange={(v) => set((g) => { g.children[j].delay_ms = v ?? 0; })} />
              )}
              {!beats && <span style={{ color: 'var(--text-muted)' }}>ms</span>}
            </label>
            {beats && (
              <Checkbox value={child.pre_ramp} label="pre-ramp"
                onChange={(v) => set((g) => { g.children[j].pre_ramp = v; })} />
            )}
            <span style={{ flex: 1 }} />
            <button title="Move up" disabled={j === 0} style={{ padding: '2px 7px', fontSize: 12 }}
              onClick={() => set((g) => {
                const [c] = g.children.splice(j, 1);
                g.children.splice(j - 1, 0, c);
              })}>↑</button>
            <button title="Duplicate step" style={{ padding: '2px 7px', fontSize: 12 }}
              onClick={() => set((g) => {
                const clone = JSON.parse(JSON.stringify(g.children[j], (k, v) => (k.startsWith('_') ? undefined : v))) as SequenceChild;
                clone.id = uuid();
                g.children.splice(j + 1, 0, clone);
              })}>⧉</button>
            <button className="danger" title="Delete step" style={{ padding: '2px 7px', fontSize: 12 }}
              onClick={() => set((g) => { g.children.splice(j, 1); })}>✕</button>
          </div>
          <div style={{ marginBottom: 6 }}>
            <LabelsInput value={child.labels} placeholder="step filter labels (optional)"
              onChange={(v) => set((g) => { g.children[j].labels = v; })} />
          </div>
          <div style={{ marginLeft: 12 }}>
            <EditableActionContainer
              containerPath={`${groupPath}.children.${j}.actions`}
              actions={child.actions}
              emptyNote="No actions — all actions in a step fire concurrently."
            />
          </div>
        </div>
      ))}
      <button style={{ fontSize: 12 }} onClick={() => set((g) => { g.children.push(newSequenceChild()); })}>
        + Add step
      </button>

      <div style={{ marginTop: 10, borderTop: '1px solid var(--border)', paddingTop: 8,
                    display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <Checkbox
          value={!!revert?.enabled}
          label="↩️ Revert after"
          onChange={(v) => set((g) => {
            if (v) g.revert = { ...(g.revert ?? defaultRevert()), enabled: true };
            else if (g.revert) g.revert.enabled = false;
          })}
        />
        {revert?.enabled && (
          <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13 }}>
            <span style={{ color: 'var(--text-muted)' }}>hold</span>
            {beats ? (
              <NumberInput value={revert.delay_beats} min={0} step={1} width={70}
                onChange={(v) => set((g) => { if (g.revert) g.revert.delay_beats = Math.max(0, Math.round(v ?? 0)); })} />
            ) : (
              <NumberInput value={revert.delay_ms} min={0} step={50} width={90}
                onChange={(v) => set((g) => { if (g.revert) g.revert.delay_ms = v ?? 0; })} />
            )}
            <span style={{ color: 'var(--text-muted)' }}>{beats ? 'beats, ramp' : 'ms, ramp'}</span>
            <NumberInput value={revert.transition_ms} min={0} step={50} width={90}
              onChange={(v) => set((g) => { if (g.revert) g.revert.transition_ms = v ?? 500; })} />
            <span style={{ color: 'var(--text-muted)' }}>ms</span>
            {beats && (
              <Checkbox value={revert.pre_ramp} label="pre-ramp"
                onChange={(v) => set((g) => { if (g.revert) g.revert.pre_ramp = v; })} />
            )}
          </label>
        )}
      </div>
    </div>
  );
}
