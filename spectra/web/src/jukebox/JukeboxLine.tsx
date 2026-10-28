/** THE JUKEBOX LINE, draggable — shared by the Guests tab and the Live tab
 * (report.md §7.2: both host views carry "the draggable line"). ONE
 * component, not two copies: a song already sent to Spotify has no handle
 * and sits in its own, undraggable list above; only the waiting songs are a
 * SortableList, and the caller's own `onReorder` is the engine's own move
 * (`POST /jukebox/line/{id}/move`) — nothing passes the sent song. */
import type { ReactNode } from 'react';
import SortableList from '../lightshow/SortableList';

export default function JukeboxLine<T>({
  items, getId, getLabel, getSent, onReorder, renderRow, className = 'jukebox-next',
}: {
  items: T[];
  getId: (item: T) => string;
  getLabel: (item: T) => string;
  getSent: (item: T) => boolean;
  /** `id` is the waiting song moving; `to` is its new place among the waiting songs. */
  onReorder: (id: string, to: number) => void;
  renderRow: (item: T) => ReactNode;
  className?: string;
}) {
  const sentRows = items.filter(getSent);
  const waitingRows = items.filter((it) => !getSent(it));
  return (
    <>
      {sentRows.length > 0 && (
        <ol className={className}>
          {sentRows.map((it) => (
            <li key={getId(it)} className="jukebox-item jukebox">{renderRow(it)}</li>
          ))}
        </ol>
      )}
      {waitingRows.length > 0 && (
        <SortableList
          className={className}
          items={waitingRows}
          getId={getId}
          getLabel={getLabel}
          onReorder={(from, to) => onReorder(getId(waitingRows[from]), to)}
          renderItem={(it, _i, row) => (
            <li ref={row.rowRef} style={row.rowStyle}
              className={`jukebox-item set${row.isDragging ? ' dragging' : ''}`}>
              {row.handle}
              {renderRow(it)}
            </li>
          )} />
      )}
    </>
  );
}
