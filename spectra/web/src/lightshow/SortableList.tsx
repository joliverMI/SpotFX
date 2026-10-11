/** Drag-and-drop ordering for the Light Show builders — the SAME library and
 * interaction model as the legacy SpotFX event editor he praised
 * (web/src/components/cards/EditActionCard.tsx: @dnd-kit/sortable, a ⠿
 * handle that starts the drag, the row lifting while the others slide out
 * of its way). Three things it keeps true:
 *
 *   * ONLY THE HANDLE DRAGS. The handle carries `touch-action: none`, so a
 *     finger on it drags while a finger anywhere else on the row still
 *     scrolls the page — the phone/tablet half of "drag on touch".
 *   * A drag starts after 6 px of movement (the legacy editor's own
 *     constraint), so a tap on the handle is never a drag.
 *   * The keyboard works too: focus the handle, Space to lift, arrows to
 *     move, Space to drop (dnd-kit's sortable keyboard coordinates).
 *
 * Rows move vertically only; the list reports `onReorder(from, to)` and the
 * caller owns the data. */
import type { CSSProperties, ReactNode } from 'react';
import {
  DndContext, KeyboardSensor, PointerSensor, closestCenter, useSensor, useSensors,
  type DragEndEvent, type Modifier,
} from '@dnd-kit/core';
import {
  SortableContext, sortableKeyboardCoordinates, useSortable, verticalListSortingStrategy,
} from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';

const verticalOnly: Modifier = ({ transform }) => ({ ...transform, x: 0 });

export interface SortableRowProps {
  /** spread onto the row's root element */
  rowRef: (el: HTMLElement | null) => void;
  rowStyle: CSSProperties;
  isDragging: boolean;
  /** the ⠿ handle — renders the handle element itself */
  handle: ReactNode;
}

function Row({ id, render, label }: {
  id: string; label: string; render: (p: SortableRowProps) => ReactNode;
}) {
  const { attributes, listeners, setNodeRef, setActivatorNodeRef, transform, transition, isDragging } =
    useSortable({ id });
  const handle = (
    <span ref={setActivatorNodeRef} {...attributes} {...listeners}
      className="light-show-step-handle" title="Drag to reorder" aria-label={`Drag to reorder ${label}`}
      onClick={(e) => e.stopPropagation()}>
      ⠿
    </span>
  );
  return (
    <>
      {render({
        rowRef: setNodeRef,
        rowStyle: {
          transform: CSS.Translate.toString(transform),
          transition,
          position: 'relative',
          zIndex: isDragging ? 5 : undefined,
        },
        isDragging,
        handle,
      })}
    </>
  );
}

export default function SortableList<T>({ items, getId, getLabel, onReorder, renderItem, className }: {
  items: T[];
  getId: (item: T, index: number) => string;
  getLabel?: (item: T, index: number) => string;
  onReorder: (from: number, to: number) => void;
  renderItem: (item: T, index: number, row: SortableRowProps) => ReactNode;
  className?: string;
}) {
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );
  const ids = items.map(getId);
  const onDragEnd = (e: DragEndEvent) => {
    if (!e.over || e.active.id === e.over.id) return;
    const from = ids.indexOf(String(e.active.id));
    const to = ids.indexOf(String(e.over.id));
    if (from >= 0 && to >= 0) onReorder(from, to);
  };
  return (
    <DndContext sensors={sensors} collisionDetection={closestCenter} modifiers={[verticalOnly]}
      onDragEnd={onDragEnd}>
      <SortableContext items={ids} strategy={verticalListSortingStrategy}>
        <ol className={className}>
          {items.map((it, i) => (
            <Row key={ids[i]} id={ids[i]} label={getLabel ? getLabel(it, i) : `item ${i + 1}`}
              render={(row) => renderItem(it, i, row)} />
          ))}
        </ol>
      </SortableContext>
    </DndContext>
  );
}
