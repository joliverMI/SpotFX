import { useState } from 'react';
import { SortableContext, verticalListSortingStrategy } from '@dnd-kit/sortable';
import { useDroppable } from '@dnd-kit/core';
import type { Action, ActionType } from '../../types/events';
import { getUid } from '../../lib/uid';
import { getAtPath } from '../../lib/paths';
import { newAction } from '../../lib/defaults';
import { useEditorStore } from '../../store/editorStore';
import EditActionCard from '../cards/EditActionCard';
import AddActionDialog from '../dialogs/AddActionDialog';

export const EDITABLE_ACTION_TYPES: ActionType[] = [
  'event_ref', 'ledfx_scene', 'ledfx_ambient', 'ledfx_ambient_color',
  'ledfx_global_brightness', 'ledfx_global_transition', 'ledfx_effect_param',
  'morph_step', 'morph_color', 'device_settings',
  'random_group', 'sequence_group', 'parallel_group',
];

/** A sortable, droppable Action[] list at `containerPath` with a "+ Add action" footer. */
export default function EditableActionContainer({
  containerPath,
  actions,
  emptyNote,
}: {
  containerPath: string;
  actions: Action[];
  emptyNote?: string;
}) {
  const [adding, setAdding] = useState(false);
  const mutate = useEditorStore((s) => s.mutate);
  const { setNodeRef, isOver } = useDroppable({ id: `container:${containerPath}` });

  return (
    <div
      ref={setNodeRef}
      style={{
        borderRadius: 8,
        outline: isOver ? '1px dashed var(--accent)' : 'none',
        outlineOffset: 2,
        minHeight: 20,
      }}
    >
      <SortableContext items={actions.map(getUid)} strategy={verticalListSortingStrategy}>
        {actions.map((a) => (
          <EditActionCard key={getUid(a)} action={a} />
        ))}
      </SortableContext>
      {!actions.length && <p className="empty-note">{emptyNote ?? 'No actions yet.'}</p>}
      <button style={{ fontSize: 12, marginTop: 2 }} onClick={() => setAdding(true)}>
        + Add action
      </button>
      {adding && (
        <AddActionDialog
          types={EDITABLE_ACTION_TYPES}
          onClose={() => setAdding(false)}
          onPick={(t) => {
            mutate((d) => {
              const arr = getAtPath(d, containerPath) as Action[];
              arr.push(newAction(t));
            });
            setAdding(false);
          }}
        />
      )}
    </div>
  );
}
