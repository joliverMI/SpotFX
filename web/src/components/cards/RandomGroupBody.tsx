import type { RandomGroupAction, RandomOption } from '../../types/events';
import { uuid } from '../../lib/uid';
import { useEditorStore } from '../../store/editorStore';
import { groupPathOf } from './groupPath';
import { Checkbox, LabelsInput, NumberInput, TextInput } from '../forms/inputs';
import EditableActionContainer from '../tracks/EditableActionContainer';

const newOption = (): RandomOption => ({ id: uuid(), name: '', labels: [], weight: 1, actions: [] });

/** Expanded body of a random_group card: weighted options, each holding a nested
 * (droppable, sortable) action list. Recursion happens naturally — options can
 * contain further random_group cards. */
export default function RandomGroupBody({ uid, action }: { uid: string; action: RandomGroupAction }) {
  const draft = useEditorStore((s) => s.draft);
  const updateAction = useEditorStore((s) => s.updateAction);
  if (!draft) return null;

  const groupPath = groupPathOf(draft, uid);
  if (!groupPath) return null;
  const set = (fn: (g: RandomGroupAction) => void) =>
    updateAction(uid, (a) => { if (a.type === 'random_group') fn(a); });

  return (
    <div style={{ marginBottom: 10 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 8 }}>
        <span style={{ fontSize: 13, color: 'var(--text-muted)' }}>
          One option is picked per fire (weighted); its actions fire together.
        </span>
        <Checkbox
          value={action.dedupe}
          label="avoid repeating last pick"
          onChange={(v) => set((g) => { g.dedupe = v; })}
        />
      </div>
      {action.options.map((opt, j) => (
        <div key={opt.id} className="action-card" style={{ padding: 10, marginBottom: 8 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, flexWrap: 'wrap' }}>
            <span className="step-badge" title="Option">{j + 1}</span>
            <TextInput value={opt.name} placeholder="option name (optional)" width={180}
              onChange={(v) => set((g) => { g.options[j].name = v; })} />
            <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13 }}>
              <span style={{ color: 'var(--text-muted)' }}>weight</span>
              <NumberInput value={opt.weight} min={0} step={0.1} width={80}
                onChange={(v) => set((g) => { g.options[j].weight = v ?? 1; })} />
            </label>
            <span style={{ flex: 1 }} />
            <button title="Duplicate option" style={{ padding: '2px 7px', fontSize: 12 }}
              onClick={() => set((g) => {
                const clone = JSON.parse(JSON.stringify(g.options[j], (k, v) => (k.startsWith('_') ? undefined : v))) as RandomOption;
                clone.id = uuid();
                g.options.splice(j + 1, 0, clone);
              })}>⧉</button>
            <button className="danger" title="Delete option" style={{ padding: '2px 7px', fontSize: 12 }}
              onClick={() => set((g) => { g.options.splice(j, 1); })}>✕</button>
          </div>
          <div style={{ marginBottom: 6 }}>
            <LabelsInput value={opt.labels} placeholder="option filter labels (optional)"
              onChange={(v) => set((g) => { g.options[j].labels = v; })} />
          </div>
          <div style={{ marginLeft: 12 }}>
            <EditableActionContainer
              containerPath={`${groupPath}.options.${j}.actions`}
              actions={opt.actions}
              emptyNote="No actions — drag cards here or add one."
            />
          </div>
        </div>
      ))}
      <button style={{ fontSize: 12 }} onClick={() => set((g) => { g.options.push(newOption()); })}>
        + Add option
      </button>
    </div>
  );
}
