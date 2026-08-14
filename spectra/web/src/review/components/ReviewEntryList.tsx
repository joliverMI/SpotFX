/** The vertical, phone-friendly twin of ReviewLaneBar: every merged
 * timeline item as a tappable row, ordered exactly as the backend
 * returned it (song position, see show_reconstruction.merge_timeline).
 * Notes stand out visually as pins against the plain event rows. */
import { useEffect, useRef } from 'react';
import { fmtMs } from '../../lib/time';
import type { ReviewTimelineItem } from '../../types';
import { describeEvent } from '../describeEvent';

export default function ReviewEntryList({
  timeline,
  selectedIndex,
  onSelect,
}: {
  timeline: ReviewTimelineItem[];
  selectedIndex: number | null;
  onSelect: (index: number) => void;
}) {
  const rowRefs = useRef<(HTMLDivElement | null)[]>([]);

  useEffect(() => {
    if (selectedIndex == null) return;
    rowRefs.current[selectedIndex]?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }, [selectedIndex]);

  if (timeline.length === 0) {
    return <p className="empty-note">Nothing reconstructed for this song yet.</p>;
  }

  return (
    <div className="review-entry-list">
      {timeline.map((item, i) => {
        const isNote = item.type === 'note';
        return (
          <div
            key={`${item.type}-${i}`}
            ref={(el) => { rowRefs.current[i] = el; }}
            className={`review-entry-row ${isNote ? 'note' : 'event'} ${i === selectedIndex ? 'selected' : ''}`}
            onClick={() => onSelect(i)}
            role="button"
            tabIndex={0}
          >
            <span className="review-entry-pos">{fmtMs(item.position_ms)}</span>
            {isNote ? (
              <span className="review-entry-note-text">📌 {item.note || '(no text)'}</span>
            ) : (
              <span className="review-entry-event-text">{describeEvent(item)}</span>
            )}
          </div>
        );
      })}
    </div>
  );
}
