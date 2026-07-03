import { useState } from 'react';
import { SortableContext } from '@dnd-kit/sortable';
import type { MusicEvent } from '../../types/events';
import { getUid } from '../../lib/uid';
import { newAction } from '../../lib/defaults';
import { useEditorStore } from '../../store/editorStore';
import EditActionCard from '../cards/EditActionCard';
import AddActionDialog from '../dialogs/AddActionDialog';
import { EDITABLE_ACTION_TYPES } from '../tracks/EditableActionContainer';

/** The composite event's tree: one root action (usually a group). The root
 * card isn't draggable/movable — everything inside it is. */
export default function RootSlot({ event }: { event: MusicEvent }) {
  const [adding, setAdding] = useState(false);
  const mutate = useEditorStore((s) => s.mutate);

  return (
    <div className="track">
      <div className="track-header">
        <span>🌳</span>
        <span>Event tree</span>
      </div>
      {event.root ? (
        <SortableContext items={[getUid(event.root)]}>
          <EditActionCard action={event.root} />
        </SortableContext>
      ) : (
        <>
          <p className="empty-note">
            Empty event — pick a root: a Sequence, Parallel, or Random group
            (or a single action).
          </p>
          <button className="primary" style={{ fontSize: 12 }} onClick={() => setAdding(true)}>
            + Set root
          </button>
        </>
      )}
      {adding && (
        <AddActionDialog
          types={EDITABLE_ACTION_TYPES}
          onClose={() => setAdding(false)}
          onPick={(t) => {
            mutate((d) => { d.root = newAction(t); });
            setAdding(false);
          }}
        />
      )}
    </div>
  );
}
