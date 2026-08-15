/** The selected item's context panel: a note read alongside the events
 * that actually surrounded it, plus Prev/Next to jump between notes
 * without hunting on the lane bar or scrolling the list by hand. */
import { fmtMs } from '../../lib/time';
import type { ReviewTimelineItem } from '../../types';
import { BUCKET_COLOR, describeEvent } from '../describeEvent';

const CONTEXT_MS = 15_000;

export default function ReviewNoteDetail({
  timeline,
  selectedIndex,
  noteIndices,
  onSelect,
}: {
  timeline: ReviewTimelineItem[];
  selectedIndex: number;
  /** Indices into `timeline` of every note item, in timeline order —
   * what Prev/Next cycle through. */
  noteIndices: number[];
  onSelect: (index: number) => void;
}) {
  const selected = timeline[selectedIndex];
  const pos = selected.position_ms;
  const context = pos == null
    ? [selected]
    : timeline.filter((item) => item.position_ms != null
        && Math.abs(item.position_ms - pos) <= CONTEXT_MS);

  const posInNotes = noteIndices.indexOf(selectedIndex);
  const prevNote = posInNotes > 0 ? noteIndices[posInNotes - 1] : null;
  const nextNote = posInNotes >= 0 && posInNotes < noteIndices.length - 1
    ? noteIndices[posInNotes + 1] : null;

  return (
    <div className="review-note-detail">
      <div className="review-note-detail-head">
        <span className="review-note-detail-title">
          {selected.type === 'note' ? '📌 Note' : 'Selected'} @ {fmtMs(pos)}
        </span>
        {noteIndices.length > 0 && (
          <span className="review-note-detail-nav">
            <button disabled={prevNote == null} onClick={() => prevNote != null && onSelect(prevNote)}>
              ◀ Prev note
            </button>
            <button disabled={nextNote == null} onClick={() => nextNote != null && onSelect(nextNote)}>
              Next note ▶
            </button>
          </span>
        )}
      </div>

      {selected.type === 'note' && (
        <p className="review-note-detail-text">{selected.note || '(no text)'}</p>
      )}

      <div className="review-note-detail-context">
        <div className="review-note-detail-context-label">
          Surrounding show (±{CONTEXT_MS / 1000}s)
        </div>
        {context.map((item, i) => (
          <div
            key={i}
            className={`review-note-detail-context-row ${item === selected ? 'selected' : ''} ${item.type}`}
          >
            <span className="review-entry-pos">{fmtMs(item.position_ms)}</span>
            {item.type === 'note'
              ? <span>📌 {item.note || '(no text)'}</span>
              : (
                <span className="review-entry-event-text">
                  <span className="trigger-color-dot" style={{ background: BUCKET_COLOR[item.bucket] }} />
                  {describeEvent(item)}
                </span>
              )}
          </div>
        ))}
      </div>
    </div>
  );
}
