import type { ParallelChild, ParallelGroupAction } from '../../types/events';
import { newParallelChild } from '../../lib/defaults';
import { uuid } from '../../lib/uid';
import { useEditorStore } from '../../store/editorStore';
import { LabelsInput, NumberInput, TextInput } from '../forms/inputs';
import EditableActionContainer from '../tracks/EditableActionContainer';
import { groupPathOf } from './groupPath';

/** Expanded body of a parallel_group card: lanes fire together, each with an
 * optional offset stagger and a nested droppable action list. */
export default function ParallelGroupBody({ uid, action }: { uid: string; action: ParallelGroupAction }) {
  const draft = useEditorStore((s) => s.draft);
  const updateAction = useEditorStore((s) => s.updateAction);
  if (!draft) return null;
  const groupPath = groupPathOf(draft, uid);
  if (!groupPath) return null;

  const set = (fn: (g: ParallelGroupAction) => void) =>
    updateAction(uid, (a) => { if (a.type === 'parallel_group') fn(a); });

  return (
    <div style={{ marginBottom: 10 }}>
      <p style={{ fontSize: 13, color: 'var(--text-muted)', marginBottom: 8 }}>
        All lanes fire together; offset staggers a lane (negative = earlier).
        Put a Random Group inside a lane for “pick one per lane”.
      </p>
      {action.children.map((child, j) => (
        <div key={child.id} className="action-card" style={{ padding: 10, marginBottom: 8 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, flexWrap: 'wrap' }}>
            <TextInput value={child.name} placeholder={`Lane ${j + 1}`} width={150}
              onChange={(v) => set((g) => { g.children[j].name = v; })} />
            <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13 }}>
              <span style={{ color: 'var(--text-muted)' }}>offset</span>
              <NumberInput value={child.offset_ms} step={10} width={90}
                onChange={(v) => set((g) => { g.children[j].offset_ms = v ?? 0; })} />
              <span style={{ color: 'var(--text-muted)' }}>ms</span>
            </label>
            <span style={{ flex: 1 }} />
            <button title="Move up" disabled={j === 0} style={{ padding: '2px 7px', fontSize: 12 }}
              onClick={() => set((g) => {
                const [c] = g.children.splice(j, 1);
                g.children.splice(j - 1, 0, c);
              })}>↑</button>
            <button title="Duplicate lane" style={{ padding: '2px 7px', fontSize: 12 }}
              onClick={() => set((g) => {
                const clone = JSON.parse(JSON.stringify(g.children[j], (k, v) => (k.startsWith('_') ? undefined : v))) as ParallelChild;
                clone.id = uuid();
                g.children.splice(j + 1, 0, clone);
              })}>⧉</button>
            <button className="danger" title="Delete lane" style={{ padding: '2px 7px', fontSize: 12 }}
              onClick={() => set((g) => { g.children.splice(j, 1); })}>✕</button>
          </div>
          <div style={{ marginBottom: 6 }}>
            <LabelsInput value={child.labels} placeholder="lane filter labels (merge with trigger labels)"
              onChange={(v) => set((g) => { g.children[j].labels = v; })} />
          </div>
          <div style={{ marginLeft: 12 }}>
            <EditableActionContainer
              containerPath={`${groupPath}.children.${j}.actions`}
              actions={child.actions}
              emptyNote="No actions — the lane is skipped."
            />
          </div>
        </div>
      ))}
      <button style={{ fontSize: 12 }} onClick={() => set((g) => { g.children.push(newParallelChild()); })}>
        + Add lane
      </button>
    </div>
  );
}
