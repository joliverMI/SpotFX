import { useState } from 'react';
import { useSortable } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import type { Action } from '../../types/events';
import { ACTION_ICONS, ACTION_TYPE_LABELS, summarizeAction } from '../../types/summaries';
import { useSummaryCtx } from '../SummaryCtx';
import { useEditorStore } from '../../store/editorStore';
import { getAtPath, findByUid } from '../../lib/paths';
import { getUid } from '../../lib/uid';
import ActionForm from '../forms/ActionForm';
import RandomGroupBody from './RandomGroupBody';
import SequenceGroupBody from './SequenceGroupBody';
import ParallelGroupBody from './ParallelGroupBody';
import { writeClip } from '../../store/clipboard';

/** Editable HA-style card: drag handle, collapsed summary ⇄ expanded form, ⧉/✕ menu. */
export default function EditActionCard({ action }: { action: Action }) {
  const [open, setOpen] = useState(false);
  const ctx = useSummaryCtx();
  const uid = getUid(action);
  const updateAction = useEditorStore((s) => s.updateAction);
  const removeByUid = useEditorStore((s) => s.removeByUid);
  const mutate = useEditorStore((s) => s.mutate);

  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: uid });

  const duplicate = () =>
    mutate((d) => {
      const loc = findByUid(d, uid);
      if (loc?.kind !== 'action') return;
      const arr = getAtPath(d, loc.containerPath) as Action[];
      const clone = JSON.parse(
        JSON.stringify(arr[loc.index], (k, v) => (k.startsWith('_') ? undefined : v)),
      ) as Action;
      arr.splice(loc.index + 1, 0, clone);
    });

  return (
    <div
      ref={setNodeRef}
      className="action-card"
      style={{
        transform: CSS.Transform.toString(transform),
        transition,
        opacity: isDragging ? 0.4 : 1,
      }}
    >
      <div className="action-card-row" onClick={() => setOpen(!open)}>
        <span
          {...attributes}
          {...listeners}
          onClick={(e) => e.stopPropagation()}
          title="Drag to reorder / move"
          style={{ cursor: 'grab', color: 'var(--text-muted)', flex: 'none', touchAction: 'none' }}
        >
          ⠿
        </span>
        <span className={`caret ${open ? 'open' : ''}`}>▶</span>
        <span className="action-card-icon">{ACTION_ICONS[action.type] ?? '❓'}</span>
        <span className="action-card-summary">{summarizeAction(action, ctx)}</span>
        {action.weight !== 1 && <span className="chip" title="Weight">w {action.weight}</span>}
        {action.labels.slice(0, 3).map((l) => (
          <span key={l} className="chip">{l}</span>
        ))}
        <span className="action-card-type">{ACTION_TYPE_LABELS[action.type] ?? action.type}</span>
        <button title="Copy (paste in any track, any event)" style={{ padding: '2px 7px', fontSize: 12 }}
          onClick={(e) => { e.stopPropagation(); writeClip('action', action, summarizeAction(action, ctx)); }}>📋</button>
        <button title="Duplicate" style={{ padding: '2px 7px', fontSize: 12 }}
          onClick={(e) => { e.stopPropagation(); duplicate(); }}>⧉</button>
        <button className="danger" title="Delete" style={{ padding: '2px 7px', fontSize: 12 }}
          onClick={(e) => { e.stopPropagation(); removeByUid(uid); }}>✕</button>
      </div>
      {open && (
        <div className="action-card-body">
          {action.type === 'random_group' && <RandomGroupBody uid={uid} action={action} />}
          {action.type === 'sequence_group' && <SequenceGroupBody uid={uid} action={action} />}
          {action.type === 'parallel_group' && <ParallelGroupBody uid={uid} action={action} />}
          <ActionForm action={action} update={(fn) => updateAction(uid, fn)} />
        </div>
      )}
    </div>
  );
}
